# Worked Example: Monthly Spend Trend

A short example of taking a SQL result into an analysis, the kind of thing a data analyst does
daily. This joins the `04_monthly_spend.sql` output to a quick visualization in Python.

```python
import sqlite3
import pandas as pd
import matplotlib.pyplot as plt

con = sqlite3.connect(":memory:")
con.executescript(open("schema.sql").read())
con.executescript(open("seed.sql").read())

df = pd.read_sql_query(open("queries/04_monthly_spend.sql").read(), con)

fig, ax = plt.subplots(figsize=(7, 4))
ax.bar(df["month"], df["monthly_spend"], label="Monthly spend")
ax.plot(df["month"], df["cumulative_spend"], color="black", marker="o", label="Cumulative")
ax.set_ylabel("USD")
ax.set_title("Reagent spend by month")
ax.legend()
fig.tight_layout()
fig.savefig("monthly_spend.png", dpi=120)
```

Result (verified 2026-07-01): three months of orders, cumulative spend reaching $2,030.
The same pattern generalizes: any operational question becomes a query, and any query result
becomes a table or chart a PI or budget office can act on.

> To turn this into a portfolio centerpiece, run the code above, commit `monthly_spend.png`,
> and embed it in the README.
