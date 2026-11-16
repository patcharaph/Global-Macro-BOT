# T7a: workflow changes that could not be pushed with this token

GitHub rejected an update to `.github/workflows/*.yml` because the `gh`
OAuth token used to open this PR does not have the `workflow` scope.
The daily and weekly *Python* jobs already write `public/latest.json`.
To publish that file on `main`, replace the workflow files with the
proposed copies in this folder (or add the `workflow` scope and land
the same diff):

- `docs/t7a-daily.yml.proposed` → `.github/workflows/daily.yml`
  (adds `permissions: contents: write` and a commit step for `public/latest.json`)
- `docs/t7a-weekly.yml.proposed` → `.github/workflows/weekly.yml`
  (adds `public/latest.json` to the existing heartbeat commit)

Until that is applied, `curl` of the raw URL will 404 even after merge,
but a local demo (`python -m flowmacro.export.snapshot --demo`) still works.
