import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { AlertCircle, Loader2, PlugZap, RefreshCw } from "lucide-react";

import type { ConnectedAccount } from "../../interfaces/job";
import { formatDate, getErrorMessage } from "../../lib/format";
import {
  deleteConnectedAccount,
  getConnectedAccounts,
  getYouTubeAuthorizeUrl,
} from "../../services/api";
import { EmptyState } from "../common/EmptyState";
import { PageHeader } from "../common/PageHeader";
import { Alert, AlertDescription, AlertTitle } from "../ui/alert";
import { Badge } from "../ui/badge";
import { Button, buttonVariants } from "../ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../ui/card";

export function ConnectorDraft({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(
    null,
  );
  const [disconnectingAccountId, setDisconnectingAccountId] = useState<
    number | null
  >(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const connectedAccountsQuery = useQuery({
    queryKey: ["connected-accounts", "youtube"],
    queryFn: () => getConnectedAccounts("youtube"),
  });

  const connectedAccounts = connectedAccountsQuery.data ?? [];
  const error = connectedAccountsQuery.error
    ? getErrorMessage(
        connectedAccountsQuery.error,
        "Unable to load connected accounts.",
      )
    : actionError;

  useEffect(() => {
    const connectedAccountId = Number(searchParams.get("youtube_connected"));
    if (!Number.isInteger(connectedAccountId) || connectedAccountId <= 0)
      return;

    setSelectedAccountId(connectedAccountId);
    const nextSearchParams = new URLSearchParams(searchParams);
    nextSearchParams.delete("youtube_connected");
    setSearchParams(nextSearchParams, { replace: true });
    void queryClient.invalidateQueries({
      queryKey: ["connected-accounts", "youtube"],
    });
  }, [queryClient, searchParams, setSearchParams]);

  useEffect(() => {
    if (selectedAccountId !== null) {
      const stillExists = connectedAccounts.some(
        (account) => account.id === selectedAccountId,
      );
      if (stillExists) return;
    }

    setSelectedAccountId(connectedAccounts[0]?.id ?? null);
  }, [connectedAccounts, selectedAccountId]);

  function handleConnectYouTube() {
    window.location.href = getYouTubeAuthorizeUrl();
  }

  async function handleDisconnectAccount(account: ConnectedAccount) {
    setActionError(null);
    setDisconnectingAccountId(account.id);
    try {
      await deleteConnectedAccount(account.id);
      if (selectedAccountId === account.id) {
        setSelectedAccountId(null);
      }
      await queryClient.invalidateQueries({
        queryKey: ["connected-accounts", account.platform],
      });
    } catch (error) {
      setActionError(
        getErrorMessage(error, "Unable to disconnect the connected account."),
      );
    } finally {
      setDisconnectingAccountId(null);
    }
  }

  return (
    <section className="grid gap-6">
      <PageHeader
        eyebrow="Connector"
        title="Connected account settings"
        description="Connect and manage upload provider accounts outside the job dashboard, then use those providers when publishing completed videos."
      />

      {Boolean(error) && (
        <Alert variant="destructive" className="bg-red-50">
          <AlertCircle />
          <AlertTitle>Connector error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card className="bg-white/90 shadow-xl shadow-slate-900/5">
        <CardHeader>
          <CardDescription>Connected API</CardDescription>
          <CardTitle className="break-all text-lg">{apiBaseUrl}</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          OAuth callbacks return to this SPA route with connector status in the
          query string.
        </CardContent>
      </Card>

      <Card className="bg-white/90 shadow-xl shadow-slate-900/5">
        <CardHeader>
          <div>
            <CardDescription className="font-black uppercase tracking-[0.18em] text-primary">
              YouTube connector
            </CardDescription>
            <CardTitle className="mt-2 text-2xl">Google account</CardTitle>
            <CardDescription>
              Connect a Google account with the YouTube upload scope. Publishing
              screens can use these saved credentials without owning connector
              setup logic.
            </CardDescription>
          </div>
          <CardAction>
            <Badge
              variant={connectedAccounts.length > 0 ? "default" : "secondary"}
            >
              {connectedAccounts.length} connected
            </Badge>
          </CardAction>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3 text-sm text-muted-foreground">
              <PlugZap className="size-4 text-primary" />
              <span>
                Authorize YouTube upload access through Core API OAuth.
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="secondary"
                disabled={connectedAccountsQuery.isFetching}
                onClick={() => void connectedAccountsQuery.refetch()}
              >
                <RefreshCw
                  className={
                    connectedAccountsQuery.isFetching ? "animate-spin" : ""
                  }
                />
                Refresh
              </Button>
              <Button type="button" onClick={handleConnectYouTube}>
                Connect YouTube
              </Button>
            </div>
          </div>

          <div className="grid gap-3">
            {connectedAccountsQuery.isLoading ? (
              <EmptyState>
                <Loader2 className="mx-auto mb-3 size-5 animate-spin" />
                Loading connected accounts…
              </EmptyState>
            ) : connectedAccounts.length > 0 ? (
              connectedAccounts.map((account) => (
                <ConnectedAccountRow
                  account={account}
                  isDisconnecting={disconnectingAccountId === account.id}
                  isSelected={selectedAccountId === account.id}
                  key={account.id}
                  onDisconnect={() => void handleDisconnectAccount(account)}
                  onSelect={() => setSelectedAccountId(account.id)}
                />
              ))
            ) : (
              <EmptyState>
                No YouTube account connected yet. Connect one here, or
                publishing can fall back to environment credentials if
                configured.
              </EmptyState>
            )}
          </div>

          <div className="rounded-2xl border bg-slate-50 p-4 text-sm text-muted-foreground">
            Finished processing a video? Go to{" "}
            <Link
              className={buttonVariants({ variant: "link", size: "sm" })}
              to="/videos"
            >
              Videos
            </Link>{" "}
            to publish completed jobs.
          </div>
        </CardContent>
      </Card>
    </section>
  );
}

function ConnectedAccountRow({
  account,
  isDisconnecting,
  isSelected,
  onDisconnect,
  onSelect,
}: {
  account: ConnectedAccount;
  isDisconnecting: boolean;
  isSelected: boolean;
  onDisconnect: () => void;
  onSelect: () => void;
}) {
  return (
    <label className="flex cursor-pointer flex-col gap-3 rounded-xl border bg-white p-3 text-sm sm:flex-row sm:items-center sm:justify-between">
      <span className="flex items-start gap-3">
        <input
          className="mt-1"
          type="radio"
          name="connected-youtube-account"
          checked={isSelected}
          onChange={onSelect}
        />
        <span>
          <strong>{account.display_name}</strong>
          <span className="mt-1 block break-all text-muted-foreground">
            Account #{account.id} · scopes: {account.scopes || "unknown"}
          </span>
          {account.expires_at && (
            <span className="mt-1 block text-muted-foreground">
              Access token expires {formatDate(account.expires_at)}
            </span>
          )}
        </span>
      </span>
      <Button
        type="button"
        variant="secondary"
        size="sm"
        disabled={isDisconnecting}
        onClick={(event) => {
          event.preventDefault();
          onDisconnect();
        }}
      >
        {isDisconnecting && <Loader2 className="animate-spin" />}
        Disconnect
      </Button>
    </label>
  );
}
