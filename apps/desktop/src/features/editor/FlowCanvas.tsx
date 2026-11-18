import { useCallback, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
  type EdgeChange,
  type NodeChange,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AlertTriangle } from "lucide-react";
import type { CanvasNode, EditorEdge, EditorNode } from "../../lib/editorTypes";
import type { StepSpec } from "../../lib/models";
import {
  connectionIssue,
  edgeIdsForIssue,
  issueCountsByStep,
  RECIPE_INPUT_HANDLE,
  recipeInputNodesAndEdges,
} from "../../lib/recipeGraph";
import { useEditorStore } from "../../stores/editorStore";
import { InputNode } from "./InputNode";
import { StepNode } from "./StepNode";
import { STEP_DRAG_MIME } from "./StepPanel";

const nodeTypes: NodeTypes = {
  step: StepNode as unknown as NodeTypes["step"],
  recipeInput: InputNode as unknown as NodeTypes["recipeInput"],
};

const defaultEdgeOptions = {
  animated: false,
  style: { strokeWidth: 1.75, stroke: "#94a3b8" },
} as const;

function CanvasInner() {
  const nodes = useEditorStore((state) => state.nodes);
  const edges = useEditorStore((state) => state.edges);
  const inputs = useEditorStore((state) => state.inputs);
  const specs = useEditorStore((state) => state.specs);
  const issues = useEditorStore((state) => state.issues);
  const applyNodes = useEditorStore((state) => state.applyNodes);
  const applyEdges = useEditorStore((state) => state.applyEdges);
  const connect = useEditorStore((state) => state.connect);
  const addStep = useEditorStore((state) => state.addStep);
  const setSelection = useEditorStore((state) => state.setSelection);
  const moveNode = useEditorStore((state) => state.moveNode);

  const [notice, setNotice] = useState<string | null>(null);
  const dragStart = useRef<Record<string, { x: number; y: number }>>({});
  const { screenToFlowPosition } = useReactFlow();

  const specsByUses = useMemo(
    () => Object.fromEntries(specs.map((spec) => [spec.id, spec])),
    [specs],
  );

  const specsByNode = useMemo(() => {
    const map: Record<string, StepSpec> = {};
    for (const node of nodes) {
      const spec = specsByUses[node.data.uses];
      if (spec) map[node.id] = spec;
    }
    return map;
  }, [nodes, specsByUses]);

  const counts = useMemo(() => issueCountsByStep(issues), [issues]);

  const inputGraph = useMemo(
    () => recipeInputNodesAndEdges(inputs, nodes, edges),
    [inputs, nodes, edges],
  );

  const runInputCounts = useMemo(() => {
    const result = new Map<string, number>();
    for (const edge of inputGraph.edges) {
      if (edge.targetHandle !== RECIPE_INPUT_HANDLE) continue;
      result.set(edge.target, (result.get(edge.target) ?? 0) + 1);
    }
    return result;
  }, [inputGraph.edges]);

  const displayNodes = useMemo<CanvasNode[]>(
    () => [
      ...nodes.map((node) => {
        const spec = specsByUses[node.data.uses];
        const count = counts[node.id] ?? { errors: 0, warnings: 0 };
        return {
          ...node,
          data: {
            ...node.data,
            inputs: spec?.inputs ?? {},
            outputs: spec?.outputs ?? {},
            requiresAgent: spec?.requires_agent ?? false,
            errorCount: count.errors,
            warningCount: count.warnings,
            runInputCount: runInputCounts.get(node.id) ?? 0,
          },
        };
      }),
      ...inputGraph.nodes,
    ],
    [nodes, specsByUses, counts, runInputCounts, inputGraph.nodes],
  );

  const edgeErrors = useMemo(() => {
    const map = new Map<string, "error" | "warning">();
    for (const issue of issues) {
      for (const id of edgeIdsForIssue(issue, edges)) {
        const severity = issue.severity === "warning" ? "warning" : "error";
        if (severity === "error" || !map.has(id)) map.set(id, severity);
      }
    }
    return map;
  }, [issues, edges]);

  const displayEdges = useMemo(
    () => [
      ...edges.map((edge) => {
        const severity = edgeErrors.get(edge.id);
        if (!severity) return edge;
        return {
          ...edge,
          animated: severity === "error",
          style: {
            strokeWidth: severity === "error" ? 2.5 : 2,
            stroke: severity === "error" ? "#ef4444" : "#f59e0b",
          },
        };
      }),
      ...inputGraph.edges,
    ],
    [edges, edgeErrors, inputGraph.edges],
  );

  const validateConnection = useCallback(
    (connection: Connection | EditorEdge): boolean => {
      if (!connection.source || !connection.target) return false;
      if (connection.source === connection.target) return false;
      return (
        connectionIssue(
          {
            source: connection.source,
            target: connection.target,
            sourceHandle: connection.sourceHandle,
            targetHandle: connection.targetHandle,
          },
          specsByNode,
        ) === null
      );
    },
    [specsByNode],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      setNotice(connect(connection));
    },
    [connect],
  );

  const stepIds = useMemo(() => new Set(nodes.map((node) => node.id)), [nodes]);

  return (
    <div className="absolute inset-0">
      <ReactFlow<CanvasNode, EditorEdge>
        nodes={displayNodes}
        edges={displayEdges}
        nodeTypes={nodeTypes}
        defaultEdgeOptions={defaultEdgeOptions}
        isValidConnection={validateConnection}
        onNodesChange={(changes: NodeChange<CanvasNode>[]) =>
          applyNodes(
            changes.filter((change) =>
              stepIds.has((change as { id?: string }).id ?? ""),
            ) as unknown as NodeChange<EditorNode>[],
          )
        }
        onEdgesChange={(changes: EdgeChange<EditorEdge>[]) => applyEdges(changes)}
        onConnect={onConnect}
        onNodeClick={(_, node) => {
          if (node.type === "recipeInput") return;
          setSelection([node.id]);
        }}
        onPaneClick={() => setSelection([])}
        onNodeDragStart={(_, _node, dragged) => {
          const stepNodes = dragged.filter((item) => item.type === "step");
          dragStart.current = Object.fromEntries(
            stepNodes.map((item) => [item.id, { ...item.position }]),
          );
          if (stepNodes.length > 0) useEditorStore.temporal.getState().pause();
        }}
        onNodeDragStop={(_, _node, dragged) => {
          const stepNodes = dragged.filter((item) => item.type === "step");
          const start = dragStart.current;
          dragStart.current = {};
          if (stepNodes.length === 0) return;
          // 拖动期间暂停记录：先把位置还原到拖动前，恢复记录后再提交最终位置，
          // 这样撤销历史里只留下“拖动前 → 拖动后”一步。
          for (const item of stepNodes) {
            const before = start[item.id];
            if (before) moveNode(item.id, before);
          }
          useEditorStore.temporal.getState().resume();
          for (const item of stepNodes) {
            moveNode(item.id, { x: item.position.x, y: item.position.y });
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          event.dataTransfer.dropEffect = "move";
        }}
        onDrop={(event) => {
          event.preventDefault();
          const uses = event.dataTransfer.getData(STEP_DRAG_MIME);
          if (!uses) return;
          const spec = specsByUses[uses];
          if (!spec) {
            setNotice(`未知步骤: ${uses}`);
            return;
          }
          const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
          addStep(spec, { x: position.x - 120, y: position.y - 50 });
        }}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        minZoom={0.2}
        maxZoom={1.8}
        selectionOnDrag
        panOnScroll
        deleteKeyCode={["Backspace", "Delete"]}
        className="bg-slate-50"
      >
        <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#cbd5e1" />
        <Controls showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          className="!bottom-3 !right-3 !h-24 !w-40 rounded-lg border border-slate-200"
          nodeColor={(node) => (node.type === "recipeInput" ? "#bae6fd" : "#e2e8f0")}
          maskColor="rgb(241 245 249 / 0.7)"
        />
      </ReactFlow>

      {notice ? (
        <div className="pointer-events-none absolute left-1/2 top-3 z-10 -translate-x-1/2">
          <p className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-800 shadow-sm">
            <AlertTriangle className="h-3.5 w-3.5" /> {notice}
          </p>
        </div>
      ) : null}

      {nodes.length === 0 ? (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
          <div className="rounded-xl border border-dashed border-slate-300 bg-white/80 px-6 py-5 text-center">
            <p className="text-sm font-medium text-slate-700">空白画布</p>
            <p className="mt-1 text-xs text-slate-500">
              从左侧拖入步骤开始搭流水线，例如 probe → extract → normalize → export。
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function FlowCanvas() {
  return (
    <ReactFlowProvider>
      <CanvasInner />
    </ReactFlowProvider>
  );
}
