//! stdout 行分类与协议数据结构（对应 PROTOCOL.md 第 2 节）。

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// JSON-RPC error 对象。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RpcErrorObject {
    pub code: i64,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub data: Option<Value>,
}

impl std::fmt::Display for RpcErrorObject {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "[{}] {}", self.code, self.message)
    }
}

/// 一行 stdout 的归类结果。
#[derive(Debug, Clone, PartialEq)]
pub enum Incoming {
    /// 响应：命中 pending 中的请求。
    Response {
        id: u64,
        result: Result<Value, RpcErrorObject>,
    },
    /// `event` 通知，params 原样转发给前端。
    Event { params: Value },
    /// 结构合法但不认识的消息（记录日志，不崩溃）。
    Other { raw_method: Option<String> },
}

/// 解析单行。解析失败由调用方记录截断后的原文。
pub fn classify(line: &str) -> Result<Incoming, serde_json::Error> {
    let value: Value = serde_json::from_str(line)?;

    if let Some(id) = value.get("id") {
        let id = match id.as_u64() {
            Some(id) => id,
            None => {
                return Ok(Incoming::Other {
                    raw_method: Some(format!("non-numeric id: {id}")),
                });
            }
        };
        if let Some(error) = value.get("error").filter(|v| !v.is_null()) {
            let error: RpcErrorObject = serde_json::from_value(error.clone())?;
            return Ok(Incoming::Response {
                id,
                result: Err(error),
            });
        }
        let result = value.get("result").cloned().unwrap_or(Value::Null);
        return Ok(Incoming::Response {
            id,
            result: Ok(result),
        });
    }

    let method = value
        .get("method")
        .and_then(Value::as_str)
        .map(str::to_owned);
    if method.as_deref() == Some("event") {
        let params = value.get("params").cloned().unwrap_or(Value::Null);
        return Ok(Incoming::Event { params });
    }

    Ok(Incoming::Other {
        raw_method: method,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_success_response() {
        let incoming = classify(r#"{"jsonrpc":"2.0","id":3,"result":{"ok":true}}"#).unwrap();
        assert_eq!(
            incoming,
            Incoming::Response {
                id: 3,
                result: Ok(serde_json::json!({"ok": true}))
            }
        );
    }

    #[test]
    fn parses_error_response() {
        let incoming = classify(
            r#"{"jsonrpc":"2.0","id":7,"error":{"code":1002,"message":"Step failed","data":{"step":"extract"}}}"#,
        )
        .unwrap();
        match incoming {
            Incoming::Response { id: 7, result: Err(err) } => {
                assert_eq!(err.code, 1002);
                assert_eq!(err.data.unwrap()["step"], "extract");
            }
            other => panic!("unexpected: {other:?}"),
        }
    }

    #[test]
    fn parses_event_notification() {
        let incoming = classify(
            r#"{"jsonrpc":"2.0","method":"event","params":{"type":"step.progress","percent":0.5}}"#,
        )
        .unwrap();
        assert_eq!(
            incoming,
            Incoming::Event {
                params: serde_json::json!({"type": "step.progress", "percent": 0.5})
            }
        );
    }

    #[test]
    fn unknown_notification_is_not_fatal() {
        let incoming = classify(r#"{"jsonrpc":"2.0","method":"ping"}"#).unwrap();
        assert_eq!(
            incoming,
            Incoming::Other {
                raw_method: Some("ping".into())
            }
        );
    }

    #[test]
    fn invalid_json_is_error() {
        assert!(classify("not json").is_err());
    }

    #[test]
    fn non_numeric_id_is_other() {
        let incoming = classify(r#"{"jsonrpc":"2.0","id":"abc","result":null}"#).unwrap();
        assert!(matches!(incoming, Incoming::Other { .. }));
    }

    #[test]
    fn truncated_log_preview_never_panics_on_utf8() {
        // 模拟日志截断：必须按字符边界处理，不能切坏 UTF-8。
        let text = "中文日志".repeat(100);
        let preview: String = text.chars().take(10).collect();
        assert_eq!(preview.chars().count(), 10);
    }
}
