import { redirect } from "next/navigation";

// Preserve old /new links while enforcing the automatic live workflow.
export default function NewInvestigationRedirect() {
  redirect("/github");
}
