import { EmptyState } from "../common/EmptyState";
import { PageHeader } from "../common/PageHeader";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../ui/card";

export function ConnectorDraft({ apiBaseUrl }: { apiBaseUrl: string }) {
  return (
    <section className="grid gap-6">
      <PageHeader
        eyebrow="Connector"
        title="Connector settings draft"
        description="Business rules for connected accounts will be added later. For now, this page reserves the connector section in the dashboard shell."
      />
      <Card className="bg-white/90 shadow-xl shadow-slate-900/5">
        <CardHeader>
          <CardDescription>Connected API</CardDescription>
          <CardTitle className="break-all text-lg">{apiBaseUrl}</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState>
            Connector page draft — business content pending.
          </EmptyState>
        </CardContent>
      </Card>
    </section>
  );
}
