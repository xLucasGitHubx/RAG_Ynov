import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./styles.css";

import { StrictMode, Suspense, lazy, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { AppShell } from "./components/AppShell";
import { LoadingBlock } from "./components/ui";
import { AssistantPage } from "./pages/Assistant";
import { NotFoundPage } from "./pages/NotFound";

// Les pages avec graphiques (Recharts) sont chargées à la demande : l'assistant reste léger.
const ProjectPage = lazy(() => import("./pages/Project").then((m) => ({ default: m.ProjectPage })));
const OverviewPage = lazy(() => import("./pages/Overview").then((m) => ({ default: m.OverviewPage })));
const CorpusPage = lazy(() => import("./pages/Corpus").then((m) => ({ default: m.CorpusPage })));
const EvaluationPage = lazy(() => import("./pages/Evaluation").then((m) => ({ default: m.EvaluationPage })));
const TestsPage = lazy(() => import("./pages/Tests").then((m) => ({ default: m.TestsPage })));
const MonitoringPage = lazy(() => import("./pages/Monitoring").then((m) => ({ default: m.MonitoringPage })));

const page = (node: ReactNode) => <Suspense fallback={<LoadingBlock />}>{node}</Suspense>;

const router = createBrowserRouter(
  [
    {
      element: <AppShell />,
      children: [
        { index: true, element: page(<OverviewPage />) },
        { path: "projet", element: page(<ProjectPage />) },
        { path: "assistant", element: <AssistantPage /> },
        { path: "corpus", element: page(<CorpusPage />) },
        { path: "evaluation", element: page(<EvaluationPage />) },
        { path: "tests", element: page(<TestsPage />) },
        { path: "monitoring", element: page(<MonitoringPage />) },
        { path: "*", element: <NotFoundPage /> },
      ],
    },
  ],
  { basename: "/ui" },
);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
