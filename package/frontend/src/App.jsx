import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import AuthGuard from './components/AuthGuard';
import './index.css';

const WelcomePage = lazy(() => import('./pages/WelcomePage'));
const LoginPage = lazy(() => import('./pages/LoginPage'));
const RegisterPage = lazy(() => import('./pages/RegisterPage'));
const ApiSettingsPage = lazy(() => import('./pages/ApiSettingsPage'));
const CreditsPage = lazy(() => import('./pages/CreditsPage'));
const ProfilePage = lazy(() => import('./pages/ProfilePage'));
const WorkspacePage = lazy(() => import('./pages/WorkspacePage'));
const SessionDetailPage = lazy(() => import('./pages/SessionDetailPage'));
const AdminDashboard = lazy(() => import('./pages/AdminDashboard'));

const RouteFallback = () => (
  <div className="flex min-h-screen items-center justify-center bg-slate-50 text-sm font-semibold text-slate-500">
    页面载入中...
  </div>
);

function App() {
  return (
    <BrowserRouter>
      <Toaster
        position="top-right"
        toastOptions={{
          duration: 3000,
          style: {
            background: '#363636',
            color: '#fff',
          },
          success: {
            duration: 3000,
            iconTheme: {
              primary: '#10B981',
              secondary: '#fff',
            },
          },
          error: {
            duration: 4000,
            iconTheme: {
              primary: '#EF4444',
              secondary: '#fff',
            },
          },
        }}
      />

      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<WelcomePage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/admin" element={<AdminDashboard />} />

          <Route
            path="/workspace"
            element={
              <AuthGuard>
                <WorkspacePage />
              </AuthGuard>
            }
          />

          <Route
            path="/profile"
            element={
              <AuthGuard>
                <ProfilePage />
              </AuthGuard>
            }
          />

          <Route
            path="/api-settings"
            element={
              <AuthGuard>
                <ApiSettingsPage />
              </AuthGuard>
            }
          />

          <Route
            path="/credits"
            element={
              <AuthGuard>
                <CreditsPage />
              </AuthGuard>
            }
          />

          <Route
            path="/session/:sessionId"
            element={
              <AuthGuard>
                <SessionDetailPage />
              </AuthGuard>
            }
          />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

export default App;
