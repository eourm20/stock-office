"use client";

import AnalysisView from "../analysis/AnalysisView";

/** Main screen: the newest decision (or the meeting in progress) with its full analysis. */
export default function Home() {
  return <AnalysisView runId={null} />;
}
