# Cloudflare deployment

The reader is deployed as a Cloudflare Pages project named `viscount`. Small
static files are uploaded to Pages, while the 149 MB audiobook is stored in the
private `viscount-audio` R2 bucket and served through a same-origin Pages
Function. The R2 bucket itself does not need public access or an `r2.dev` URL.

## One-time account setup

Install the pinned Wrangler version and sign in through Cloudflare's OAuth flow:

```bash
npm install
npx wrangler login
```

Create the private bucket and upload the audio object:

```bash
npm run cloudflare:create-bucket
npm run cloudflare:upload-audio
```

Create the Pages project with `main` as its production branch:

```bash
npx wrangler pages project create viscount --production-branch main
```

## Build, test, and deploy

```bash
npm run build:cloudflare
npm run test:cloudflare
npm run deploy:cloudflare
```

The build copies only the web reader, alignment map, manifest, icon, and service
worker into `artifacts/deploy/cloudflare-pages`. It deliberately excludes the audiobook so
the Pages 25 MiB per-file limit is not exceeded. Its `_routes.json` invokes the
Function only for `/audio/*`; HTML and other static requests retain Pages'
unlimited static-request treatment.

## Custom domain

In the Cloudflare dashboard, open **Workers & Pages**, select **viscount**, open
**Custom domains**, and choose **Set up a domain**. Enter
`viscount.spanashis.com`. Because `spanashis.com` is already a Cloudflare zone,
Cloudflare should create the required DNS record and certificate automatically.

## Non-interactive authentication

Local deployment does not require an API token when `wrangler login` is used.
For CI or another non-interactive environment, set these environment variables
outside the repository:

```text
CLOUDFLARE_ACCOUNT_ID=...
CLOUDFLARE_API_TOKEN=...
```

Use a scoped API token rather than the Global API Key. It needs Cloudflare Pages
Edit and Workers R2 Storage Edit access on the relevant account. DNS Edit on the
`spanashis.com` zone is only needed if the custom-domain DNS record will be
managed through the API rather than through the Pages dashboard flow.

## Local Pages preview

```bash
npm run dev:cloudflare
```

Wrangler uses a local R2 store by default. To exercise audio locally through the
Pages Function, place an object with the production key into Wrangler's local R2
bucket, or continue to use `uv run python scripts/serve_reader.py` for the
existing artifact-based development server. The npm development command also
prevents Wrangler from injecting this repository's unrelated `.env` values into
the local Pages Function.
