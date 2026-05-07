import { apiBaseUrl } from "../../services/api";

import { ConnectorDraft } from "./ConnectorDraft";

export default function ConnectorPage() {
  return <ConnectorDraft apiBaseUrl={apiBaseUrl} />;
}
