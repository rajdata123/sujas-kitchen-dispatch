# Suja's Kitchen — Daily Dispatch Automation

Turns the 7 daily branch order PDFs into: 7 branch dispatch workbooks (matching your
existing "Food Dispatch Time & Temperature Log" format) + 2 chef requisition
reports (Meals/Snacks, as an image and as Excel) — with a simple web page,
no command line needed.

## What's inside
```
app.py                 Streamlit web app (the UI Shapan uses)
src/pdf_parser.py       Reads the ERP order PDFs into structured data
src/item_master.py      Loads/saves the item -> bucket/storage lookup table
src/dispatch_sheet.py   Builds each branch's 2-tab dispatch workbook
src/chef_report.py      Builds the Meals/Snacks matrix + PNG image
src/adjustments.py      Applies WhatsApp add/remove/set-qty requests
data/item_master.csv    The lookup table — all 118 known items tagged and
                         verified against all 7 branches' real dispatch
                         sheets, zero left for manual tagging on day one
assets/fonts/           Bundled fonts so the chef-report image renders
                         correctly on any hosting, not just this machine
requirements.txt        Python packages needed
```

## Item Master status: fully mapped

`data/item_master.csv` was built from all 7 branches' order PDFs and all 7
branches' dispatch sheets you shared — 118 unique items, every one matched
to its bucket + storage zone with zero conflicts across branches. Nothing
is guessed: this is a direct reproduction of how you've already been
categorizing these items. Day one starts with nothing flagged.

New items will still show up automatically the first time they appear in
a future order (the "Tag new items" step only appears when needed) — that's
by design, not a gap: it's how the system stays accurate as your item
catalog grows, without you having to remember to update anything.

## Built to flex with real-world messiness

A few things that won't break the workflow, by design:
- **Any number of branches, any day** — upload 3 PDFs or 9, the system
  generates exactly what's uploaded. Nothing is hardcoded to "7".
- **A brand-new branch or a renamed one** — flagged clearly rather than
  silently mis-filed; add its keyword to `BRANCH_KEYWORDS` in
  `src/pdf_parser.py` (one line) once, and it's recognized forever after.
- **A bad or unrelated PDF in the batch** — that one file is skipped with a
  clear error; every other file in the same upload still goes through.
- **A brand-new bucket/storage zone** you type while tagging an item (via
  "+ New group..." / "+ New storage...") — shows up correctly in the
  generated sheets and chef report, not silently dropped.
- **Two PDFs for the same branch uploaded together** — flagged as a
  warning (likely a duplicate upload) rather than silently duplicating
  that branch's items.

## Deploying it (free, so Shapan just opens a link)

Recommended: **Streamlit Community Cloud** (streamlit.io/cloud) — free,
takes about 5 minutes, no server to maintain.

1. Create a free GitHub account if you don't have one, and push this whole
   folder to a new **private** repo (e.g. `sujas-kitchen-dispatch`).
2. Go to share.streamlit.io, sign in with GitHub, click "New app", pick
   that repo, and set the main file to `app.py`.
3. Deploy. You'll get a permanent URL like
   `https://sujas-kitchen-dispatch.streamlit.app` — bookmark it and send it
   to Shapan. That's what he opens every day, from any device, no install.

Notes:
- The app "naps" after ~15 min of no visitors and takes ~20-30 seconds to
  wake up on the next visit — normal for the free tier, not a bug.
- **Item Master persistence**: tags Shapan adds during the day are saved to
  `data/item_master.csv` on the app's own storage, which normally survives
  fine between daily uses — but a redeploy or a long sleep can occasionally
  reset it. Use the "Download backup" button in the app's sidebar
  periodically (e.g. weekly) so you always have a safe copy to restore from
  if that ever happens.

If you'd rather I walk you through the GitHub + Streamlit Cloud steps live,
or you want to hand me a repo to push to directly, just say so.

## Running it yourself to test first (optional)

```
pip install -r requirements.txt
streamlit run app.py
```
Opens at `http://localhost:8501`.
