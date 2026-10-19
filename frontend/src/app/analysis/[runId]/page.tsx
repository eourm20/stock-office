"use client";

import { useParams } from "next/navigation";
import AnalysisView from "../../../analysis/AnalysisView";

/** One run's analysis, shareable by URL. */
export default function AnalysisPage() {
  const { runId } = useParams<{ runId: string }>();
  return <AnalysisView runId={runId} />;
}
