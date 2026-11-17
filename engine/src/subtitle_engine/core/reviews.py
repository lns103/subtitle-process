"""人工审核（HITL）持久化与暂停信号（TASKBOOK §5.6 / M5）。

审核不是阻塞请求：``human.review`` 步骤把待审项写入 SQLite，然后抛出
:class:`ReviewPending`。Runner 捕获后把 run 置为 ``waiting_review`` 并保存
断点；``review.submit`` 写入决策后调用 ``JobManager.resume`` 继续执行。
"""

from __future__ import annotations

import logging
import uuid

from .models import Review, ReviewDecision, ReviewItem, utc_now
from .store import Store

logger = logging.getLogger(__name__)


class ReviewPending(Exception):
    """步骤请求暂停等待人工审核；由 Runner 转为 ``waiting_review``。"""

    def __init__(self, review_id: str, items: list[ReviewItem]) -> None:
        super().__init__(f"等待人工审核: {review_id}")
        self.review_id = review_id
        self.items = items


class ReviewStore:
    """``Store`` 之上的审核记录门面。"""

    def __init__(self, store: Store) -> None:
        self._store = store

    @staticmethod
    def new_review_id() -> str:
        return f"rv_{uuid.uuid4().hex[:10]}"

    @staticmethod
    def new_item_id(review_id: str, position: int) -> str:
        return f"rev_{review_id[3:]}_{position:04d}"

    def save(self, review: Review) -> Review:
        review.updated_at = utc_now()
        self._store.save_review(review)
        return review

    def get(self, review_id: str) -> Review | None:
        return self._store.get_review(review_id)

    def require(self, review_id: str) -> Review:
        review = self.get(review_id)
        if review is None:
            raise KeyError(f"审核记录不存在: {review_id}")
        return review

    def list_for_run(self, run_id: str) -> list[Review]:
        return self._store.list_reviews(run_id)

    def find(self, run_id: str, step_id: str | None = None) -> Review | None:
        """返回某次 run（可限定步骤）的最新审核记录。"""
        reviews = [
            item
            for item in self.list_for_run(run_id)
            if step_id is None or item.step_id == step_id
        ]
        return reviews[-1] if reviews else None

    def pending(self, run_id: str) -> Review | None:
        for review in reversed(self.list_for_run(run_id)):
            if review.status == "pending":
                return review
        return None

    def submit(self, review: Review, decisions: list[ReviewDecision]) -> Review:
        """记录决策并标记已提交；实际应用由步骤在续跑时完成。"""
        known = {item.id for item in review.items}
        unknown = [decision.id for decision in decisions if decision.id not in known]
        if unknown:
            raise ValueError(f"决策引用了不存在的审核项: {', '.join(unknown[:5])}")
        by_id = {decision.id: decision for decision in decisions}
        for item in review.items:
            decision = by_id.get(item.id)
            if decision is None or decision.action == "reject":
                item.status = "rejected"
            else:
                item.status = "accepted"
        review.decisions = decisions
        review.status = "submitted"
        return self.save(review)


__all__ = ["ReviewPending", "ReviewStore"]
