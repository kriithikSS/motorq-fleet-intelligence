'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('admin@motorq.com');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<'fleet_admin' | 'driver' | 'auditor'>('fleet_admin');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError('');

    // Demo: accept any non-empty password
    await new Promise(r => setTimeout(r, 800));

    if (!password) {
      setError('Password is required');
      setLoading(false);
      return;
    }

    // In production: POST /api/auth/token with username + password
    // Store JWT in httpOnly cookie via API route
    if (typeof window !== 'undefined') {
      localStorage.setItem('motorq_role', role);
      localStorage.setItem('motorq_user', email);
    }
    router.push('/');
  }

  const demoAccounts = [
    { role: 'fleet_admin' as const, email: 'admin@motorq.com', label: 'Fleet Admin', color: '#3b82f6' },
    { role: 'driver' as const, email: 'driver@motorq.com', label: 'Driver', color: '#10b981' },
    { role: 'auditor' as const, email: 'auditor@motorq.com', label: 'Auditor', color: '#8b5cf6' },
  ];

  return (
    <div style={{
      minHeight: '100vh',
      background: 'var(--bg-primary)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 24,
    }}>
      {/* Background glow */}
      <div style={{
        position: 'fixed', inset: 0, pointerEvents: 'none',
        background: 'radial-gradient(ellipse at 20% 50%, rgba(59,130,246,0.08) 0%, transparent 60%), radial-gradient(ellipse at 80% 20%, rgba(6,182,212,0.06) 0%, transparent 50%)'
      }} />

      <div style={{ width: '100%', maxWidth: 420, position: 'relative' }}>
        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: 40 }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
            <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#06b6d4', boxShadow: '0 0 16px #06b6d4' }} />
            <span style={{ fontSize: 28, fontWeight: 800, background: 'linear-gradient(135deg,#3b82f6,#06b6d4)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
              Motorq
            </span>
          </div>
          <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>Fleet Intelligence Platform</p>
        </div>

        {/* Card */}
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 16, padding: 32 }}>
          <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 6 }}>Sign in</h1>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 24 }}>Access your fleet dashboard</p>

          {/* Demo quick-select */}
          <div style={{ marginBottom: 24 }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Demo accounts</div>
            <div style={{ display: 'flex', gap: 8 }}>
              {demoAccounts.map(acc => (
                <button
                  key={acc.role}
                  onClick={() => { setRole(acc.role); setEmail(acc.email); setPassword('demo123'); }}
                  style={{
                    flex: 1,
                    padding: '8px 4px',
                    borderRadius: 8,
                    border: `1px solid ${role === acc.role ? acc.color : 'var(--border)'}`,
                    background: role === acc.role ? `${acc.color}18` : 'transparent',
                    color: role === acc.role ? acc.color : 'var(--text-secondary)',
                    fontSize: 11,
                    fontWeight: 600,
                    cursor: 'pointer',
                    transition: 'all 0.15s',
                  }}
                >
                  {acc.label}
                </button>
              ))}
            </div>
          </div>

          <form onSubmit={handleLogin}>
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--text-secondary)', marginBottom: 6 }}>Email</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                style={{
                  width: '100%',
                  background: 'var(--bg-secondary)',
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  padding: '10px 14px',
                  color: 'var(--text-primary)',
                  fontSize: 14,
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
                required
              />
            </div>

            <div style={{ marginBottom: 24 }}>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--text-secondary)', marginBottom: 6 }}>Password</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="Enter password (demo: demo123)"
                style={{
                  width: '100%',
                  background: 'var(--bg-secondary)',
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  padding: '10px 14px',
                  color: 'var(--text-primary)',
                  fontSize: 14,
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
                required
              />
            </div>

            {error && (
              <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#f87171', marginBottom: 16 }}>
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              style={{
                width: '100%',
                background: loading ? 'var(--border)' : 'linear-gradient(135deg,#1e40af,#0891b2)',
                color: 'white',
                border: 'none',
                borderRadius: 8,
                padding: '12px',
                fontSize: 14,
                fontWeight: 600,
                cursor: loading ? 'not-allowed' : 'pointer',
                transition: 'all 0.2s',
              }}
            >
              {loading ? 'Signing in…' : 'Sign in →'}
            </button>
          </form>

          <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 20, textAlign: 'center' }}>
            Click a demo account above then Sign in
          </p>
        </div>
      </div>
    </div>
  );
}
