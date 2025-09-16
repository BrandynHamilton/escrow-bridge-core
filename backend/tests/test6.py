import requests
import pandas as pd
from chartengineer import ChartMaker

BACKEND_URL = "http://localhost:4284"  

r = requests.get(f"{BACKEND_URL}/events")
r.raise_for_status()

data = r.json()

print(data)

df = pd.DataFrame(data["events"])

print(df)

df.set_index("createdAt", inplace=True)
df.index = pd.to_datetime(df.index)

base_df = df[df["network"] == "base-sepolia"]
blockdag_df = df[df["network"] == "blockdag-testnet"]

base_df[['amountRequestedTokens', 'amountRequestedUsd']] = base_df[['amountRequestedTokens', 'amountRequestedUsd']] / 1e6

blockdag_df['amountRequestedTokens'] = blockdag_df['amountRequestedTokens'] / 1e18
blockdag_df['amountRequestedUsd'] = blockdag_df['amountRequestedUsd'] / 1e6

cm = ChartMaker(shuffle_colors=True)
cm.build(
    df=base_df,
    axes_data = dict(y1=['amountRequestedUsd']),
    title="Base-Sepolia Volume",
    chart_type="bar",
    options={
        "tickprefix": {"y1": "$"},
        "annotations": True,
        "texttemplate": "%{label}<br>%{percent}"
    }
)
cm.add_title(subtitle="As of 2025-04-01")
cm.fig.show()

cm = ChartMaker(shuffle_colors=True)
cm.build(
    df=blockdag_df,
    axes_data = dict(y1=['amountRequestedUsd']),
    title="BlockDAG Testnet Volume",
    chart_type="bar",
    options={
        "tickprefix": {"y1": "$"},
        "annotations": True,
        "texttemplate": "%{label}<br>%{percent}"
    }
)
cm.add_title(subtitle="As of 2025-04-01")
cm.fig.show()

combined_df = pd.concat([base_df[['network','amountRequestedUsd']], blockdag_df[['network','amountRequestedUsd']]])

cm = ChartMaker(shuffle_colors=True)
cm.build(
    df=combined_df,
    groupby_col="network",
    num_col="amountRequestedUsd",
    title="Volume by Blockchain",
    chart_type="bar",
    options={
        "tickprefix": {"y1": "$"},
        "annotations": True,
        "texttemplate": "%{label}<br>%{percent}"
    }
)
cm.add_title(subtitle="As of 2025-04-01")
cm.fig.show()