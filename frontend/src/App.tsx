import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import Layout from "./Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Cases from "./pages/Cases";
import NewCase from "./pages/NewCase";
import CaseDetail from "./pages/CaseDetail";
import DemoLab from "./pages/DemoLab";
import Evaluation from "./pages/Evaluation";
import AuditLog from "./pages/AuditLog";
import About from "./pages/About";
import { Spinner } from "./ui";

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <div style={{ display: "grid", placeItems: "center", height: "100%" }}><Spinner size={30} /></div>;
  if (!user) return <Routes><Route path="*" element={<Login />} /></Routes>;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="cases" element={<Cases />} />
        <Route path="cases/new" element={<NewCase />} />
        <Route path="cases/:id" element={<CaseDetail />} />
        <Route path="demo" element={<DemoLab />} />
        <Route path="evaluation" element={<Evaluation />} />
        <Route path="audit" element={<AuditLog />} />
        <Route path="about" element={<About />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
