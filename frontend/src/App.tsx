import { useCallback, useEffect, useState } from "react";
import { NeedsYouBanner, OfflineBanner, Sidebar, TopBar, type View } from "./components/Shell";
import { DeskView } from "./views/DeskView";
import { ApprovalsView } from "./views/ApprovalsView";
import { FinanceView } from "./views/FinanceView";
import { ActivityView } from "./views/ActivityView";
import { useBoard } from "./state/BoardContext";

const VIEWS: View[] = ["desk", "approvals", "finance", "activity"];

function readHash(): { view: View; ticket: number | null } {
  const [v, t] = window.location.hash.replace(/^#\/?/, "").split("/");
  return { view: VIEWS.includes(v as View) ? (v as View) : "desk", ticket: t ? Number(t) || null : null };
}

export default function App() {
  const { activeRun } = useBoard();
  const [route, setRoute] = useState(readHash);

  useEffect(() => {
    const onHash = () => setRoute(readHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = useCallback((view: View, ticket: number | null = route.ticket) => {
    window.location.hash = view === "desk" && ticket ? `/desk/${ticket}` : `/${view}`;
  }, [route.ticket]);

  const ticket = route.ticket ?? activeRun?.ticket_id ?? null;

  return (
    <div className="app">
      <Sidebar view={route.view} onNavigate={(v) => go(v)} />
      <div className="main">
        <TopBar view={route.view} onNavigate={(v) => go(v)} />
        <OfflineBanner />
        {route.view !== "approvals" && <NeedsYouBanner onNavigate={(v) => go(v)} />}
        <main className={`view view-${route.view}`} key={route.view}>
          {route.view === "desk" && <DeskView selectedId={ticket} onSelect={(id) => go("desk", id)} onOpenApprovals={() => go("approvals")} />}
          {route.view === "approvals" && <ApprovalsView onOpenTicket={(id) => go("desk", id)} />}
          {route.view === "finance" && <FinanceView />}
          {route.view === "activity" && <ActivityView />}
        </main>
      </div>
    </div>
  );
}
