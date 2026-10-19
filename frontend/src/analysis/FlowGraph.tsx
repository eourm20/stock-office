"use client";

import { Background, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps }
  from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import { ACTION_KO } from "../office/explain";
import { agentName } from "../office/names";
import { FLOW_EDGES, FLOW_NODES, formatDuration, type AgentSummary, type NodeStatus } from "./model";

const STATUS_STYLE: Record<NodeStatus, { ring: string; label: string }> = {
  done: { ring: "border-emerald-400/80", label: "완료" },
  running: { ring: "border-sky-300 animate-pulse", label: "진행 중" },
  failed: { ring: "border-rose-400", label: "실패" },
  pending: { ring: "border-[var(--line)]", label: "대기" },
  skipped: { ring: "border-dashed border-[var(--line)] opacity-50", label: "참여 안 함" },
};

const ACTION_TEXT: Record<string, string> = {
  BUY: "text-emerald-300", SELL: "text-rose-300", HOLD: "text-sky-200", REVIEW: "text-amber-300",
};

type AgentData = { summary: AgentSummary; selected: boolean };
type DecisionData = { action: string | null };

function AgentNode({ data }: NodeProps<Node<AgentData>>) {
  const { summary: s, selected } = data;
  const style = STATUS_STYLE[s.status];
  return (
    <div className={`w-[146px] rounded-lg border-2 bg-[var(--panel)] px-2 py-1.5 text-left text-[11px] shadow
                     ${style.ring} ${selected ? "ring-2 ring-[#ffd98a]" : ""}`}>
      <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0 !bg-[var(--line)]" />
      <div className="truncate font-semibold text-[12px] text-[var(--ink)]">{agentName(s.agentId)}</div>
      <div className="flex justify-between text-[var(--muted)]">
        <span>{style.label}{s.turns > 1 ? ` · ${s.turns}회` : ""}</span>
        <span>{s.status === "done" ? formatDuration(s.durationMs) : ""}</span>
      </div>
      {s.lookups.length > 0 && (
        <div className="text-amber-200">🔍 자료 조회 {s.lookups.length}회</div>
      )}
      <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0 !bg-[var(--line)]" />
    </div>
  );
}

function DecisionNode({ data }: NodeProps<Node<DecisionData>>) {
  const a = data.action;
  return (
    <div className="w-[110px] rounded-lg border-2 border-[#ffd98a] bg-[#2a2310] px-2 py-2 text-center">
      <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0 !bg-[#ffd98a]" />
      <div className="text-[10px] text-[var(--muted)]">최종 결정</div>
      <div className={`text-base font-bold ${a ? ACTION_TEXT[a] ?? "" : "text-[var(--muted)]"}`}>
        {a ? ACTION_KO[a]?.label ?? a : "없음"}
      </div>
    </div>
  );
}

const nodeTypes = { agent: AgentNode, decision: DecisionNode };
const COL_W = 168;
const ROW_H = 72;

/**
 * The committee as a graph. Layout is fixed (stages left → right); colours and counts come only
 * from the stored events through `summarizeAgents`. Clicking a node selects that agent.
 */
export default function FlowGraph({ agents, action, selected, onSelect }: {
  agents: Record<string, AgentSummary>;
  action: string | null;
  selected: string | null;
  onSelect: (agentId: string) => void;
}) {
  const nodes = useMemo<Node[]>(() => FLOW_NODES.map(({ id, col, row }) => {
    const position = { x: col * COL_W, y: row * ROW_H };
    if (id === "decision") return { id, type: "decision", position, data: { action } };
    return { id, type: "agent", position, data: { summary: agents[id]!, selected: id === selected } };
  }), [agents, action, selected]);

  const edges = useMemo<Edge[]>(() => FLOW_EDGES.map((e) => {
    const src = agents[e.source];
    const active = e.source === "portfolio_manager" ? action !== null
      : src?.status === "done" && agents[e.target]?.status !== "skipped";
    return {
      id: `${e.source}->${e.target}`, source: e.source, target: e.target,
      animated: false,
      style: {
        stroke: e.kind === "debate" ? "#ffd98a" : active ? "#5cddb3" : "#2b3952",
        strokeDasharray: e.kind === "flow" ? undefined : "4 4",
        strokeWidth: active ? 1.6 : 1,
        opacity: active || e.kind === "debate" ? 0.9 : 0.5,
      },
    };
  }), [agents, action]);

  return (
    <div className="h-[380px] w-full" aria-hidden="true">
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView
                 fitViewOptions={{ padding: 0.04 }} minZoom={0.3} maxZoom={1.5}
                 nodesDraggable={false} nodesConnectable={false} elementsSelectable={false}
                 zoomOnScroll={false} preventScrolling={false}
                 onNodeClick={(_, node) => { if (node.id !== "decision") onSelect(node.id); }}
                 colorMode="dark">
        <Background gap={24} size={1} color="#1d2a42" />
      </ReactFlow>
    </div>
  );
}
