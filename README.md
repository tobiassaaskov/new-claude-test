# Hotel Deal Scout

An AI agent that searches the web every morning for **hotels for sale in France within a €25 million budget**, scores each one against your investment brief, and publishes the results to a dashboard on GitHub Pages.

> **Everything here is public.** Anyone can see this repository and its GitHub Pages dashboard, including the hotels being tracked, the AI's assessments and the brief. Keeping it private needs a private repository and a different host for the dashboard (see [the design doc](docs/hotel-deal-scout.md#55-access-for-the-team)).

## How it works

1. Every day at 07:15 Paris time, GitHub Actions runs `python -m scout`.
2. Claude searches the French web for hotels for sale. It gives extra attention to one region each day and skips listings it already knows.
3. For each new listing, Claude opens the page and extracts the facts: rooms, stars, deal type, price, revenue and EBITDA. It scores the hotel from 0 to 100 against [`config/brief.md`](config/brief.md) and lists reasons, red flags and questions for the broker. Hotels asking more than €25m are marked over budget.
4. The run also checks BODACC, France's official business bulletin, for hotel businesses in insolvency proceedings or being sold.
5. Results are saved in [`data/`](data), so git keeps the full history, and the dashboard is republished.

## Set-up (about five minutes)

1. **Add your Claude API key.** In this repository go to **Settings → Secrets and variables → Actions → New repository secret**. Name it `ANTHROPIC_API_KEY` and paste a key from [platform.claude.com](https://platform.claude.com/).
2. **Switch on GitHub Pages.** Go to **Settings → Pages → Build and deployment** and set **Source** to **GitHub Actions**.
3. **Run it once.** Go to **Actions → Daily hotel scout → Run workflow**. A run takes about 5–20 minutes. The dashboard then appears at <https://tobiassaaskov.github.io/new-claude-test/>.

From then on it runs by itself every morning. If a run fails, GitHub emails you, and the dashboard's **Run log** tab shows what went wrong.

## Working with your team

- Share the dashboard link. Anyone with the link can view it.
- To discuss a hotel, select **Discuss with the team** on its card. This opens a GitHub issue for that hotel.
- To set a hotel's status, add a label starting with `status:` to its issue, for example `status: shortlist`, `status: contacted` or `status: rejected`. The next run shows the status on the card.
- Only collaborators can add labels. Invite your team under **Settings → Collaborators**.

## Changing what it looks for

| File | What it controls |
|---|---|
| [`config/brief.md`](config/brief.md) | What counts as a good hotel, in plain language. After editing it, run the workflow with **Also re-assess hotels scored with an older version of the brief** ticked. |
| [`config/settings.toml`](config/settings.toml) | Budget, cost limits, focus regions, sites the agent won't open, and the Claude model. |
| [`.github/workflows/daily-scout.yml`](.github/workflows/daily-scout.yml) | What time it runs. |

## Costs

- **GitHub Actions and Pages:** free for a public repository.
- **Claude API:** roughly $1–4 per daily run, about $30–120 a month. That covers web searches at $10 per 1,000 plus tokens on Claude Opus 5.5. The dashboard's **Run log** shows the estimated cost of each run. To spend less, lower `max_web_searches` and `max_new_assessments` in `config/settings.toml`.
- New API accounts start with low rate limits. If runs report rate-limit errors, lower those same numbers or wait for your usage tier to rise.

## Limits

- AI assessments can be wrong or out of date. Check the listing and talk to the broker before relying on anything.
- The agent doesn't open leboncoin or SeLoger pages, because French courts have ruled against scraping them. Use those sites' own email alerts instead.
- Public listings are only part of the hotel market. Register your criteria with hotel brokers too.
- GitHub can start scheduled runs a few minutes late.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest                 # runs without network access or an API key
python -m scout --skip-claude    # BODACC notices and team statuses only
```

To preview the dashboard locally:

```bash
mkdir -p _site/data && cp -r site/. _site/ && cp data/*.json _site/data/
python -m http.server --directory _site
```

The design, options considered, data sources and legal notes are in [docs/hotel-deal-scout.md](docs/hotel-deal-scout.md).
