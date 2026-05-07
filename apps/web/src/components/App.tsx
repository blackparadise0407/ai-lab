import { BrowserRouter } from "react-router-dom";

import { AppLayout } from "./layout/AppLayout";
import { AppProviders } from "./providers/AppProviders";
import { AppRoutes } from "./routes/AppRoutes";

export function AppProvider() {
  return (
    <AppProviders>
      <BrowserRouter>
        <AppLayout>
          <AppRoutes />
        </AppLayout>
      </BrowserRouter>
    </AppProviders>
  );
}
