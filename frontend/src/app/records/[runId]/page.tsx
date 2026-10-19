"use client";

import { useParams } from "next/navigation";
import MinutesView from "../../../analysis/MinutesView";

export default function MinutesPage() {
  const { runId } = useParams<{ runId: string }>();
  return <MinutesView runId={runId} />;
}
