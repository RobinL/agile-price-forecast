// Public measurement ID shared with robinlinacre.com and Buslens; not a secret.
export const MEASUREMENT_ID = "G-94373ZKHEE";

type AnalyticsWindow = Window & {
  dataLayer?: IArguments[];
  gtag?: (...args: unknown[]) => void;
};

// Tests can enable this explicitly while intercepting all Google requests.
// Development visits and local previews are excluded by default.
export function setupAnalytics(
  enabled = import.meta.env.PROD &&
    ["www.robinlinacre.com", "robinlinacre.com"].includes(location.hostname),
) {
  if (!enabled || document.getElementById("google-analytics")) return;
  const analytics = window as AnalyticsWindow;
  analytics.dataLayer = analytics.dataLayer || [];
  analytics.gtag = function (..._args: unknown[]) {
    analytics.dataLayer!.push(arguments);
  };
  const tag = analytics.gtag;
  tag("consent", "default", {
    ad_storage: "denied",
    ad_user_data: "denied",
    ad_personalization: "denied",
  });
  tag("js", new Date());
  tag("config", MEASUREMENT_ID, {
    allow_google_signals: false,
    allow_ad_personalization_signals: false,
    cookie_prefix: "agile_forecast",
    cookie_path: "/agile-price-forecast/",
    cookie_domain: location.hostname,
    cookie_expires: 180 * 24 * 60 * 60,
    cookie_update: false,
    // Avoid forwarding arbitrary query strings or fragment contents.
    page_location: `${location.origin}${location.pathname}`,
    page_referrer: document.referrer ? new URL(document.referrer).origin : "",
  });
  const script = document.createElement("script");
  script.id = "google-analytics";
  script.async = true;
  script.src = `https://www.googletagmanager.com/gtag/js?id=${MEASUREMENT_ID}`;
  document.head.append(script);
}
