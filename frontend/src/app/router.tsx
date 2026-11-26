import { Navigate, createBrowserRouter } from "react-router";

import { AiLeaderPage } from "../ai-leader/AiLeaderPage";
import { OperatorPage } from "../operator/OperatorPage";
import { SupervisorPage } from "../supervisor/SupervisorPage";
import { Layout } from "./Layout";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/operator" replace /> },
      { path: "operator", element: <OperatorPage /> },
      { path: "supervisor", element: <SupervisorPage /> },
      { path: "ai-leader", element: <AiLeaderPage /> },
    ],
  },
]);
