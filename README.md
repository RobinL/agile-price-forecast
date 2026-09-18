# Agile price forecast

**[View the live forecast](https://www.robinlinacre.com/agile-price-forecast/)**

An experimental website showing a week of half-hourly Agile electricity prices in aligned daily charts, with optional highlights for the cheapest periods. Published prices are shown where available; the model estimates the rest.

Prices are for Region G, including VAT and excluding standing charges. Forecasts can be wrong or delayed: check published prices with your supplier before relying on them.

## How it works

- **Data:** free price, demand and generation feeds from Octopus Energy, NESO and Elexon.
- **Forecasting:** Python combines several tree models and adjustments. GitHub Actions refreshes the forecast hourly and retrains the model approximately weekly.
- **Storage:** private history and saved models live in Cloudflare R2.
- **Website:** Vite, TypeScript and Vega-Lite, hosted as static files on GitHub Pages. Visitors never access R2 or run the model.

## Try it locally

With Node 22.12 or newer:

```sh
npm ci
make dev
```

Open <http://127.0.0.1:5173>. This uses fictional example data, so working on the website needs no API credentials or cloud setup.

## Acknowledgements and licence

Thank you to [AgilePredict](https://agilepredict.com/) for making its [forecasting code](https://github.com/fboundy/agile_predict) available. Our model builds substantially on that work, adapting parts of the published code and adding models and adjustments. This project focuses on making forecasts easy to read at a glance, rather than claiming better forecast accuracy.

Our original code and documentation use the [MIT licence](LICENSE). AgilePredict’s [MIT notice](notices/AgilePredict-MIT.txt) is preserved. Third-party software and data retain their own terms; see [data attribution](DATA_ATTRIBUTION.md) and the [licensing review](DATA_LICENSING.md).

## More detail

- [Architecture](proposed_architecture.md)
- [Cloud setup and operating instructions](CLOUD_SETUP.md)
- [Model validation and limitations](MODEL_VALIDATION.md)
- [Research background](RESEARCH.md)
- [Local development commands](Makefile)
