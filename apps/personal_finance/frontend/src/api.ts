import { Category, DashboardData, Transaction } from './types';

const BASE_URL = 'http://127.0.0.1:8000';

export async function fetchHealth(): Promise<{ status: string }> {
  const res = await fetch(`${BASE_URL}/health`);
  if (!res.ok) throw new Error('Health check failed');
  return res.json();
}

export async function fetchCategories(): Promise<Category[]> {
  const res = await fetch(`${BASE_URL}/api/categories`);
  if (!res.ok) throw new Error('Failed to fetch categories');
  return res.json();
}

export async function fetchDashboard(year?: number, month?: number): Promise<DashboardData> {
  const params = new URLSearchParams();
  if (year) params.append('year', year.toString());
  if (month) params.append('month', month.toString());
  const res = await fetch(`${BASE_URL}/api/dashboard?${params.toString()}`);
  if (!res.ok) throw new Error('Failed to fetch dashboard');
  return res.json();
}

export async function fetchTransactions(type?: string, category_id?: number): Promise<Transaction[]> {
  const params = new URLSearchParams();
  if (type) params.append('type', type);
  if (category_id) params.append('category_id', category_id.toString());
  const res = await fetch(`${BASE_URL}/api/transactions?${params.toString()}`);
  if (!res.ok) throw new Error('Failed to fetch transactions');
  return res.json();
}

export async function createTransaction(data: {
  date: string;
  amount_rupees: number;
  type: string;
  category_id: number;
  payment_mode?: string;
  notes?: string;
}): Promise<Transaction> {
  const res = await fetch(`${BASE_URL}/api/transactions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to create transaction' }));
    throw new Error(err.detail || 'Failed to create transaction');
  }
  return res.json();
}

export async function deleteTransaction(id: number): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/transactions/${id}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('Failed to delete transaction');
}

