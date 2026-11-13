import React, { useEffect, useState } from 'react';
import { createTransaction, deleteTransaction, fetchCategories, fetchDashboard, fetchTransactions } from './api';
import { Category, DashboardData, Transaction } from './types';

export default function App() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [selectedType, setSelectedType] = useState<string>('all');
  const [selectedCategory, setSelectedCategory] = useState<number | undefined>(undefined);
  
  // Form State
  const [formDate, setFormDate] = useState<string>(new Date().toISOString().split('T')[0]);
  const [formType, setFormType] = useState<'income' | 'expense'>('expense');
  const [formCategoryId, setFormCategoryId] = useState<number>(0);
  const [formAmount, setFormAmount] = useState<string>('');
  const [formNotes, setFormNotes] = useState<string>('');
  const [formPaymentMode, setFormPaymentMode] = useState<string>('UPI');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const loadData = async () => {
    try {
      setLoading(true);
      const [cats, dash, txs] = await Promise.all([
        fetchCategories(),
        fetchDashboard(),
        fetchTransactions(selectedType === 'all' ? undefined : selectedType, selectedCategory)
      ]);
      setCategories(cats);
      setDashboard(dash);
      setTransactions(txs);
      if (cats.length > 0 && formCategoryId === 0) {
        const firstExpense = cats.find(c => c.type === 'expense') || cats[0];
        setFormCategoryId(firstExpense.id);
      }
    } catch (err: any) {
      console.error(err);
      setErrorMsg(err.message || 'Failed to load finance data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [selectedType, selectedCategory]);

  const handleCreateTransaction = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    const amountNum = parseFloat(formAmount);
    if (isNaN(amountNum) || amountNum <= 0) {
      setErrorMsg('Amount must be a positive number greater than 0.');
      return;
    }
    if (!formCategoryId) {
      setErrorMsg('Please select a valid category.');
      return;
    }

    try {
      await createTransaction({
        date: formDate,
        amount_rupees: amountNum,
        type: formType,
        category_id: formCategoryId,
        payment_mode: formPaymentMode,
        notes: formNotes,
      });
      setFormAmount('');
      setFormNotes('');
      await loadData();
    } catch (err: any) {
      setErrorMsg(err.message || 'Error creating transaction');
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Are you sure you want to delete this transaction?')) return;
    try {
      await deleteTransaction(id);
      await loadData();
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to delete transaction');
    }
  };

  const filteredCategories = categories.filter(c => c.type === formType);

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px' }}>
      <header style={{ marginBottom: 32, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontSize: 28, fontWeight: 700, color: '#f8fafc' }}>Expense Tracker & Personal Finance</h1>
          <p style={{ color: '#94a3b8', marginTop: 4 }}>Track expenses, budgets, savings and categories with rupee precision</p>
        </div>
        <div style={{ background: '#1e293b', padding: '8px 16px', borderRadius: 8, border: '1px solid #334155' }}>
          <span style={{ fontSize: 13, color: '#10b981', fontWeight: 600 }}>● Live System Ready</span>
        </div>
      </header>

      {errorMsg && (
        <div style={{ background: '#7f1d1d', color: '#fecaca', padding: '12px 16px', borderRadius: 8, marginBottom: 20 }}>
          {errorMsg}
        </div>
      )}

      {/* Metrics Row */}
      {dashboard && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16, marginBottom: 32 }}>
          <div style={{ background: '#1e293b', padding: 20, borderRadius: 12, border: '1px solid #334155' }}>
            <span style={{ fontSize: 13, color: '#94a3b8' }}>Total Income</span>
            <div style={{ fontSize: 26, fontWeight: 700, color: '#10b981', marginTop: 8 }}>
              ₹{dashboard.total_income_rupees.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div style={{ background: '#1e293b', padding: 20, borderRadius: 12, border: '1px solid #334155' }}>
            <span style={{ fontSize: 13, color: '#94a3b8' }}>Total Expenses</span>
            <div style={{ fontSize: 26, fontWeight: 700, color: '#ef4444', marginTop: 8 }}>
              ₹{dashboard.total_expense_rupees.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div style={{ background: '#1e293b', padding: 20, borderRadius: 12, border: '1px solid #334155' }}>
            <span style={{ fontSize: 13, color: '#94a3b8' }}>Net Savings</span>
            <div style={{ fontSize: 26, fontWeight: 700, color: dashboard.net_savings_rupees >= 0 ? '#38bdf8' : '#f87171', marginTop: 8 }}>
              ₹{dashboard.net_savings_rupees.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div style={{ background: '#1e293b', padding: 20, borderRadius: 12, border: '1px solid #334155' }}>
            <span style={{ fontSize: 13, color: '#94a3b8' }}>Savings Rate</span>
            <div style={{ fontSize: 26, fontWeight: 700, color: '#a855f7', marginTop: 8 }}>
              {dashboard.savings_rate_pct}%
            </div>
          </div>
        </div>
      )}

      {/* Main Grid: Form + Category Breakdown */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginBottom: 32 }}>
        {/* Form Card */}
        <div style={{ background: '#1e293b', padding: 24, borderRadius: 12, border: '1px solid #334155' }}>
          <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 16 }}>Add New Transaction</h2>
          <form onSubmit={handleCreateTransaction}>
            <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
              <button
                type="button"
                onClick={() => { setFormType('expense'); const c = categories.find(x => x.type === 'expense'); if (c) setFormCategoryId(c.id); }}
                style={{
                  flex: 1, padding: '10px 0', borderRadius: 8, border: 'none', fontWeight: 600, cursor: 'pointer',
                  background: formType === 'expense' ? '#ef4444' : '#334155', color: '#fff'
                }}
              >
                Expense
              </button>
              <button
                type="button"
                onClick={() => { setFormType('income'); const c = categories.find(x => x.type === 'income'); if (c) setFormCategoryId(c.id); }}
                style={{
                  flex: 1, padding: '10px 0', borderRadius: 8, border: 'none', fontWeight: 600, cursor: 'pointer',
                  background: formType === 'income' ? '#10b981' : '#334155', color: '#fff'
                }}
              >
                Income
              </button>
            </div>

            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 6 }}>Category</label>
              <select
                value={formCategoryId}
                onChange={e => setFormCategoryId(Number(e.target.value))}
                style={{ width: '100%', padding: 10, background: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#f8fafc' }}
              >
                {filteredCategories.map(c => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
              <div>
                <label style={{ display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 6 }}>Amount (₹)</label>
                <input
                  type="number"
                  step="0.01"
                  required
                  placeholder="250.00"
                  value={formAmount}
                  onChange={e => setFormAmount(e.target.value)}
                  style={{ width: '100%', padding: 10, background: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#f8fafc' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 6 }}>Date</label>
                <input
                  type="date"
                  required
                  value={formDate}
                  onChange={e => setFormDate(e.target.value)}
                  style={{ width: '100%', padding: 10, background: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#f8fafc' }}
                />
              </div>
            </div>

            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 6 }}>Payment Mode</label>
              <select
                value={formPaymentMode}
                onChange={e => setFormPaymentMode(e.target.value)}
                style={{ width: '100%', padding: 10, background: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#f8fafc' }}
              >
                <option value="UPI">UPI</option>
                <option value="CARD">Card</option>
                <option value="NETBANKING">Net Banking</option>
                <option value="CASH">Cash</option>
              </select>
            </div>

            <div style={{ marginBottom: 20 }}>
              <label style={{ display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 6 }}>Notes</label>
              <input
                type="text"
                placeholder="Optional notes..."
                value={formNotes}
                onChange={e => setFormNotes(e.target.value)}
                style={{ width: '100%', padding: 10, background: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#f8fafc' }}
              />
            </div>

            <button
              type="submit"
              style={{
                width: '100%', padding: '12px 0', background: '#6366f1', color: '#fff',
                border: 'none', borderRadius: 8, fontWeight: 600, cursor: 'pointer'
              }}
            >
              Add {formType === 'income' ? 'Income' : 'Expense'}
            </button>
          </form>
        </div>

        {/* Categories Breakdown */}
        <div style={{ background: '#1e293b', padding: 24, borderRadius: 12, border: '1px solid #334155' }}>
          <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 16 }}>Monthly Expense Breakdown</h2>
          {dashboard?.categories_breakdown.length === 0 ? (
            <p style={{ color: '#94a3b8', fontSize: 14 }}>No expenses recorded this month.</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {dashboard?.categories_breakdown.map(b => (
                <div key={b.category_id}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
                    <span style={{ fontWeight: 500 }}>{b.category_name}</span>
                    <span style={{ color: '#94a3b8' }}>₹{b.total_rupees.toFixed(2)} ({b.percentage_of_total}%)</span>
                  </div>
                  <div style={{ height: 8, background: '#334155', borderRadius: 4, overflow: 'hidden' }}>
                    <div style={{ width: `${b.percentage_of_total}%`, height: '100%', background: b.category_color }} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Transactions List */}
      <div style={{ background: '#1e293b', padding: 24, borderRadius: 12, border: '1px solid #334155' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h2 style={{ fontSize: 18, fontWeight: 600 }}>Transactions</h2>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={() => setSelectedType('all')}
              style={{
                padding: '6px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
                background: selectedType === 'all' ? '#6366f1' : '#334155', color: '#fff', fontSize: 13
              }}
            >
              All
            </button>
            <button
              onClick={() => setSelectedType('expense')}
              style={{
                padding: '6px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
                background: selectedType === 'expense' ? '#ef4444' : '#334155', color: '#fff', fontSize: 13
              }}
            >
              Expenses
            </button>
            <button
              onClick={() => setSelectedType('income')}
              style={{
                padding: '6px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
                background: selectedType === 'income' ? '#10b981' : '#334155', color: '#fff', fontSize: 13
              }}
            >
              Income
            </button>
          </div>
        </div>

        {transactions.length === 0 ? (
          <p style={{ color: '#94a3b8', fontSize: 14 }}>No transactions found.</p>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #334155', color: '#94a3b8', textAlign: 'left' }}>
                <th style={{ padding: '10px 8px' }}>Date</th>
                <th style={{ padding: '10px 8px' }}>Category</th>
                <th style={{ padding: '10px 8px' }}>Payment</th>
                <th style={{ padding: '10px 8px' }}>Notes</th>
                <th style={{ padding: '10px 8px', textAlign: 'right' }}>Amount</th>
                <th style={{ padding: '10px 8px', textAlign: 'center' }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map(t => (
                <tr key={t.id} style={{ borderBottom: '1px solid #2d3748' }}>
                  <td style={{ padding: '12px 8px' }}>{t.date}</td>
                  <td style={{ padding: '12px 8px' }}>
                    <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: t.category_color, marginRight: 8 }} />
                    {t.category_name}
                  </td>
                  <td style={{ padding: '12px 8px', color: '#94a3b8' }}>{t.payment_mode}</td>
                  <td style={{ padding: '12px 8px', color: '#94a3b8' }}>{t.notes || '-'}</td>
                  <td style={{ padding: '12px 8px', textAlign: 'right', fontWeight: 600, color: t.type === 'income' ? '#10b981' : '#ef4444' }}>
                    {t.type === 'income' ? '+' : '-'}₹{t.amount_rupees.toFixed(2)}
                  </td>
                  <td style={{ padding: '12px 8px', textAlign: 'center' }}>
                    <button
                      onClick={() => handleDelete(t.id)}
                      style={{ background: 'transparent', border: 'none', color: '#f87171', cursor: 'pointer', fontSize: 12 }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

