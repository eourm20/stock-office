import { redirect } from "next/navigation";

/** Old meeting list: now the records tab. */
export default function OldHistoryPage() {
  redirect("/records");
}
