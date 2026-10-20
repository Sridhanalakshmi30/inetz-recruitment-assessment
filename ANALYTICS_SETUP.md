# Live analytics tools

The candidate MySQL tab now executes SQL through `/api/candidate/analytics/query`.
It never falls back to the recruitment database account.

1. A MySQL administrator must run `analytics-setup.sql`, replacing the password placeholder first.
2. Add the restricted account connection to `.env`:

   `ANALYTICS_DATABASE_URL=mysql+pymysql://inetz_analytics_reader:URL_ENCODED_PASSWORD@127.0.0.1:3306/inetz_analytics_practice`

3. Restart FastAPI. Candidates can use SELECT and WITH queries with joins, grouping, and aggregations. Statements are read-only, capped at two seconds and 200 returned rows. The service rejects accounts with broader privileges or roles.

Python runs real Pyodide Python in an opaque-origin iframe and module worker. Run executes the edited source and displays stdout and errors. Stop terminates that run. Each run starts fresh; runtime loading allows 90 seconds and execution allows 10 seconds. The first run requires internet access to the pinned Pyodide CDN runtime. Browser memory limits apply. This does not run candidate code in the FastAPI process. NumPy/pandas imports are loaded from the runtime CDN.

For Microsoft Power BI, obtain the secure **File > Embed report > Website or portal** URL and add it to `.env`:

`POWERBI_EMBED_URL=https://app.powerbi.com/reportEmbed?reportId=...&groupId=...&autoAuth=true`

Restart FastAPI. Each viewer must sign in to Microsoft with permission and the required license/capacity. This supports report viewing/filtering, not creating reports or DAX authoring. Authoring needs a separately configured Power BI workspace/application with edit permissions and embed authentication. Do not use Publish to web for private assessment data. Sign-in popups or leaving the page may trigger the existing exam focus warnings; complete Microsoft sign-in before a timed exam.

These tools currently provide live practice runs, not scored analytics submissions. The existing three algorithm submission endpoints remain separate. MySQL and Power BI display a setup message until their connections are provided; no canned output is displayed.
