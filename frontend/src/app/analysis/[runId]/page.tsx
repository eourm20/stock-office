import { redirect } from "next/navigation";

/** Old address of a run's analysis: now the meeting minutes. */
export default async function OldAnalysisPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  redirect(`/records/${runId}`);
}
