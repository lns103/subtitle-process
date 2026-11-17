import { useEffect, useState } from "react";
import { EditorPage } from "./features/editor/EditorPage";
import { ReviewPage } from "./features/review/ReviewPage";
import { SettingsPage } from "./features/settings/SettingsPage";
import { TaskPage } from "./features/tasks/TaskPage";
import { onEngineEvent, onEngineStatus } from "./lib/events";
import type { Project } from "./lib/models";
import { getEngineStatus, type EngineStatus } from "./lib/rpc";
import { useHashRoute } from "./lib/router";
import { useProjectStore } from "./stores/projectStore";
import { useRunStore } from "./stores/runStore";

export default function App() {
  const [status, setStatus] = useState<EngineStatus>({ state: "starting" });
  const route = useHashRoute();

  useEffect(() => {
    let disposed = false;
    const cleanups: Array<() => void> = [];

    void getEngineStatus().then((value) => {
      if (!disposed) setStatus(value);
    });
    void onEngineStatus((value) => setStatus(value)).then((fn) => {
      if (disposed) fn();
      else cleanups.push(fn);
    });
    void onEngineEvent((event) => {
      useRunStore.getState().applyEvent(event);
      if (event.type === "project.updated" && event.project) {
        useProjectStore.getState().applyUpdate(event.project as Project);
      }
    }).then((fn) => {
      if (disposed) fn();
      else cleanups.push(fn);
    });

    void useProjectStore.getState().refresh();

    return () => {
      disposed = true;
      cleanups.forEach((fn) => fn());
    };
  }, []);

  if (route.name === "editor") {
    return <EditorPage initialRecipeId={route.recipeId} paths={[]} />;
  }

  if (route.name === "review") {
    return <ReviewPage runId={route.runId} />;
  }

  if (route.name === "settings") {
    return <SettingsPage />;
  }

  return (
    <TaskPage
      engineStatus={status}
      initialTaskId={route.name === "task" ? route.taskId : null}
    />
  );
}
