# Free-tier limits and eligibility

Verified against official documentation on **2026-11-14**. No account, subscription, card, trial, paid add-on, or automatic upgrade was activated. These are published allowances, not measurements of an owner's account. Recheck the dashboard and terms before provisioning.

## Vercel Hobby: eligibility is a release gate

Hobby permits **non-commercial personal use only**. Vercel defines commercial use as financial gain by anyone involved, including paid employees or consultants, payment collection, and advertising a product or service. A commercial CropTwist deployment therefore cannot use Hobby simply because traffic is small. Owner confirmation or Vercel's written eligibility determination is required even for a preview intended for commercial use. Do not activate Pro or a trial to work around this restriction. [1] [2]

Published Hobby monthly allowances are 100 GB Fast Data Transfer, 10 GB Fast Origin Transfer, 1,000,000 CDN requests, 1,000,000 function invocations, 4 active CPU hours, 360 GB-hours provisioned memory, 5,000 image transformations, 300,000 image-cache reads and 100,000 image-cache writes. Hobby runtime logs retain one hour. Most exceeded allowances block the feature until 30 days pass rather than charging overage. [1]

Build limits are one concurrent deployment, 100 deployments per day, 45 minutes per build, 2 build vCPUs and 8 GB build memory. CLI source uploads are capped at 100 MB and 15,000 files; Basic build cache is 1.5 GB. External rewrites time out after 120 seconds. The application must submit asynchronous processing and poll genuine job state; this timeout is not permission to move Python jobs into Next.js. There is no separate monthly build-minute entitlement listed on these limit pages. [1] [3]

## Supabase Free

Free includes two active projects, a 500 MB database per project, shared CPU and up to 0.5 GB RAM, 1 GB file storage, 5 GB uncached egress and 5 GB cached egress. Do not combine cached and uncached allowances into interchangeable bandwidth. Free projects pause after one week of inactivity. Storage maximum file upload size is 50 MB; image transformations are not included. Raster scenes and generated products must be measured before choosing this storage: a single object above 50 MB is a hard incompatibility, not a reason to truncate scientific data. [4]

Nano's published database connection maximum is 60 and shared pooler maximum is 200 clients. These are different limits; reserved platform connections also consume capacity. Initial application pools should be small, with bounded overflow, and total connections budgeted across API processes, workers, migrations and platform services. Nano disk baseline is 5 MB/s and 250 IOPS, with temporary bursting—not guaranteed sustained raster throughput. [5]

Free Auth includes 50,000 monthly active users. Free Edge Functions include 500,000 invocations; this does not provide a Python worker runtime. Realtime includes 200 peak concurrent connections and 2 million messages per month; its connection allowance is not PostgreSQL's pooler limit. Database/API logs retain one day; Auth audit logs retain one hour. [4]

Automatic backups and point-in-time recovery are **not included** in Free. Take encrypted off-site logical dumps and separately back up private object contents. Database backups only contain storage metadata, not storage files. Free branching is not included; use disposable local databases and, if quota permits, a separate free staging project. IPv4 direct-connect add-on, dedicated pooler, custom domain, PITR, and compute upgrades are not permitted by this task. [4] [6] [7]

## Render Free: API staging candidate only

Render explicitly says not to use Free instances for production. Free web services have 512 MB RAM, 750 instance hours per workspace per calendar month shared between services, 15-minute inactivity spin-down, roughly one-minute cold starts, arbitrary restarts, and ephemeral files lost at restart, redeploy and spin-down. They have no persistent disk or free background-worker/cron/one-off-job service. There is no guaranteed continuous worker here. [8] [9]

Hobby workspace pricing currently lists 5 GB outbound bandwidth/month and 500 standard build pipeline minutes/month. Overage is chargeable **if a payment method exists**. Without a payment method, bandwidth exhaustion suspends free services and build-minute exhaustion disables further builds. Require a cardless $0 Hobby workspace and explicit `plan: free` compute. If the account already has billing enabled, stop and have the owner establish a separate eligible no-payment workspace; configuration alone cannot prevent account-level charges. Do not provision extra custom domains beyond the two included. [8] [9]

Render can suspend Free services for unusually high service-initiated internet traffic, specifically including external databases, APIs and object storage. Supabase connections and satellite transfers may trigger this; no threshold is published, so compatibility is conditional. The official pricing page does not state an exact Free CPU allocation; do not promise a specific vCPU fraction. A 512 MB API/raster memory fit has not been established by provider documentation. [8] [9]

## $0 decision

Vercel plus Supabase is a prepared foundation, not a complete verified zero-cost production system. **There is no validated all-managed $0 production topology for the current full workload.** Render is a conditional isolated API staging option after security, durable-storage, memory and lifecycle gates pass. Continuous Python workers and retained private raster/report files require an owner-provided existing always-on host with adequate resources, or remain blocked. Existing hardware can avoid a new hosting subscription, but electricity, connectivity and operational availability are not guaranteed free. No paid fallback is activated and no fake successful processing is introduced.

## References

[1]: https://vercel.com/docs/plans/hobby "Vercel Hobby Plan"
[2]: https://vercel.com/docs/limits/fair-use-guidelines "Vercel Fair Use Guidelines"
[3]: https://vercel.com/docs/limits "Vercel Limits"
[4]: https://supabase.com/pricing "Supabase Pricing and Fees"
[5]: https://supabase.com/docs/guides/platform/compute-add-ons "Supabase Compute and Disk"
[6]: https://supabase.com/docs/guides/platform/backups "Supabase Database Backups"
[7]: https://supabase.com/docs/guides/database/connecting-to-postgres "Connect to Supabase Postgres"
[8]: https://render.com/docs/free "Deploy for Free on Render"
[9]: https://render.com/pricing "Render Pricing"
