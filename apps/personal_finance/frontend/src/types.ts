export type TransactionType = 'income' | 'expense';

export interface Category {
  id: number;
  name: string;
  type: TransactionType;
  icon: string;
  color: string;
  created_at: string;
}

export interface Transaction {
  id: number;
  date: string;
  amount_paise: number;
  amount_rupees: number;
  formatted_amount: string;
  type: TransactionType;
  category_id: number;
  category_name: string;
  category_color: string;
  payment_mode: string;
  notes: string;
  created_at: string;
}

export interface CategoryBreakdown {
  category_id: number;
  category_name: string;
  category_color: string;
  type: string;
  total_paise: number;
  total_rupees: number;
  percentage_of_total: number;
}

export interface MonthlySummary {
  year: number;
  month: number;
  total_income_paise: number;
  total_income_rupees: number;
  total_expense_paise: number;
  total_expense_rupees: number;
  net_savings_paise: number;
  net_savings_rupees: number;
  savings_rate_pct: number;
}

export interface DashboardData {
  total_income_rupees: number;
  total_expense_rupees: number;
  net_savings_rupees: number;
  savings_rate_pct: number;
  categories_breakdown: CategoryBreakdown[];
  recent_transactions: Transaction[];
  monthly_summary: MonthlySummary;
}
