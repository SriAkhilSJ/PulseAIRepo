import React, { useEffect, useState } from "react";
import Layout from "./components/Layout";
import Overview from "./views/Overview";
import Sessions from "./views/Sessions";
import SessionTrace from "./views/SessionTrace";
import ContextHealth from "./views/ContextHealth";
import Usage from "./views/Usage";
import Approvals from "./views/Approvals";
import Errors from "./views/Errors";
import Settings from "./views/Settings";
import { useApi, useStream } from "./lib/api";
import type { Health } from "./lib/types";

const useHash = () => {
  const [hash, setHash] = useState(location.hash || "#/");
  useEffect(() => {
    const fn = () => setHash(location.hash || "#/");
    window.addEventListener("hashchange", fn);
    return () => window.removeEventListener("hashchange", fn);
  }, []);
  return hash;
};

export default function App() {
  const route = useHash();
  const health = useApi<Health>("/api/health", [], 15000);
  const { events, connected } = useStream(60);

  let view: React.ReactNode;
  if (route.startsWith("#/sessions/")) {
    view = <SessionTrace id={decodeURIComponent(route.slice("#/sessions/".length))} />;
  } else if (route.startsWith("#/sessions")) {
    view = <Sessions />;
  } else if (route.startsWith("#/context")) {
    view = <ContextHealth />;
  } else if (route.startsWith("#/usage")) {
    view = <Usage />;
  } else if (route.startsWith("#/approvals")) {
    view = <Approvals />;
  } else if (route.startsWith("#/errors")) {
    view = <Errors />;
  } else if (route.startsWith("#/settings")) {
    view = <Settings health={health.data} />;
  } else {
    view = <Overview health={health.data} ticker={events.slice(0, 14)} connected={connected} />;
  }

  return (
    <Layout route={route} health={health.data} live={connected}>
      {view}
    </Layout>
  );
}
