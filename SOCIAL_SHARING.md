# Social previews and analytics

The public HTML contains Open Graph and Twitter card metadata, including the
absolute URL of `preview.png`. Link-sharing sites can read these without running
the chart JavaScript. Whether a particular Reddit post displays a thumbnail
still depends on Reddit's cache and the community's settings.

## Refreshing the preview

`web/preview.png` is a 1200×630 screenshot of two real forecast charts. It is
labelled as an example with the original forecast issue time. It is a fixed
illustration, not another live forecast endpoint. Keeping it fixed avoids adding
a browser installation to every hourly Actions job.

To regenerate it from the live site:

```sh
npm ci
PLAYWRIGHT_BROWSERS_PATH=.cache/ms-playwright npx playwright install chromium
npm run social-preview
```

Inspect the image before committing it. The script uses the real chart UI and
values; only the capture layout and example caption change. Vite includes the
reviewed image in each build, and the publication check requires its PNG format
and dimensions. Social services may retain an older preview after replacement.

## Google Analytics

The site uses public GA4 measurement ID `G-94373ZKHEE`, already used by
`robinlinacre.com` and Buslens. This identifier belongs in frontend code and
requires no secret. Filter reports by page path `/agile-price-forecast/` to
separate this project from the other sites.

The Google script loads directly on the production domain, without a consent
prompt. Analytics cookies last up to 180 days and use a project-specific prefix
and path to avoid altering the main site's cookies.

Advertising storage, advertising personalisation and Google Signals are
disabled. Page URLs sent to Analytics omit query strings and fragments;
referrers are reduced to their origin. Forecast refreshes do not generate extra
page views. Development and browser tests never send analytics measurements.

The domain's existing Cloudflare analytics is separate and unchanged. No Worker,
public R2 route, Google account setting or additional paid service is created.
See Google's [configuration](https://developers.google.com/analytics/devguides/collection/ga4/reference/config)
guidance. Browser tests intercept Google requests, so testing does not add visits
to the real analytics property.
