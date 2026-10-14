import { Link } from "react-router";
import { EmptyState, PageHeader } from "../components/ui";

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Page introuvable." />
      <EmptyState
        title="Cette adresse ne correspond à aucune page."
        action={
          <Link to="/" className="text-sm font-medium text-accent-ink underline-offset-4 hover:underline">
            Revenir à la vue d'ensemble
          </Link>
        }
      />
    </>
  );
}
