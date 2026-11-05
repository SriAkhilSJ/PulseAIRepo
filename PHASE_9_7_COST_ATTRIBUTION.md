# PHASE 9.7 COST ATTRIBUTION REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Module:** `src/finops/attribution.py`  

## 1. ATTRIBUTION CAPABILITIES

The `CostAttributionEngine` decomposes token consumption and expenditures into multi-dimensional perspectives:
- **By Task (`task_id`):** Reveals which agent tasks consume the highest proportion of project budget.
- **By Workspace (`workspace_id`):** Provides enterprise multi-tenancy cost tracking per repository folder.
- **By Model (`model`):** Evaluates model cost distribution and identifies opportunities for economical substitutions.
- **By Provider (`provider`):** Tracks spending across OpenAI, Anthropic, Google, DeepSeek, Groq, and Velona.
- **By Time Bucket (`hourly`, `daily`, `monthly`):** Aggregates burn rate trends across calendar intervals.

## 2. TOP SPENDING DRIVER ANALYSIS (PARETO)

The engine provides `get_top_spending_drivers(limit, dimension)` to immediately highlight the 20% of operations responsible for 80% of costs, facilitating targeted optimizations.
