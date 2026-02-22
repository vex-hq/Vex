# Licensing

Vex uses a dual-license model.

## SDKs — Apache 2.0

The client SDKs are licensed under the Apache License 2.0:

- `sdk/python/` — [PyPI: vex-sdk](https://pypi.org/project/vex-sdk/)
- `sdk/typescript/` — [npm: @vex_dev/sdk](https://www.npmjs.com/package/@vex_dev/sdk)

You can use, modify, and distribute the SDKs freely in any project, commercial or otherwise, with no copyleft obligations.

## Core Engine & Dashboard — AGPLv3

Everything else — the verification engine, ingestion API, alert service, dashboard, and all supporting services — is licensed under the GNU Affero General Public License v3.0:

- `services/` — All backend microservices
- `nextjs-application/` — Dashboard and landing page

You can self-host the entire Vex stack for free. If you modify the AGPLv3 components and offer them as a network service, you must make your modifications available under AGPLv3.

## Commercial License

If the AGPL doesn't work for your organization, we offer commercial licenses that remove the copyleft requirement. Contact **sales@tryvex.dev** for details.

## Managed Cloud

The easiest way to use Vex is our managed cloud at [app.tryvex.dev](https://app.tryvex.dev). No self-hosting, no license obligations — just `pip install vex-sdk` and point at our API.

## Contributing

By submitting a pull request, you agree that your contributions to AGPLv3-licensed components may be dual-licensed by Vex AI, Inc. under both AGPLv3 and a commercial license. SDK contributions remain under Apache 2.0.
