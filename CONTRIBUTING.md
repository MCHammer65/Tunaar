# Contributing to Tunaar

Thanks for your interest in improving Tunaar! A few ground rules keep the
project healthy and keep **dual-licensing** possible (Tunaar is AGPL-3.0 but
also offered commercially).

## Licensing of contributions

Tunaar is licensed under **AGPL-3.0-or-later**. By submitting a contribution
(a pull request, patch, or any other work) you agree to **both** of the
following:

1. **Developer Certificate of Origin (DCO).** You certify the DCO (below) by
   adding a `Signed-off-by` line to each commit.
2. **Contributor License Agreement (CLA).** You grant the project maintainer a
   perpetual, worldwide, royalty-free license to use your contribution, **and
   the right to relicense it** — including under the AGPL-3.0 and under a
   separate commercial license. You retain copyright to your contribution; this
   is a license grant, not an assignment. This is what allows Tunaar to be
   offered commercially alongside the open-source version. The full terms are
   in **[CLA.md](CLA.md)**.

The CLA is enforced automatically: the first time you open a pull request, the
**CLA Assistant** bot will ask you to sign by posting a one-line comment. Your
PR can't be merged until it's signed (you only sign once). If you can't agree to
the CLA, please open an issue to discuss before sending code.

### Signing off your commits

Add a sign-off to every commit (this asserts the DCO):

```bash
git commit -s -m "Your message"
```

which appends:

```
Signed-off-by: Your Name <your.email@example.com>
```

Use your real name and a valid email. Unsigned commits can't be merged.

### Developer Certificate of Origin 1.1

```
By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I have the right
    to submit it under the open source license indicated in the file; or
(b) The contribution is based upon previous work that, to the best of my
    knowledge, is covered under an appropriate open source license and I have
    the right under that license to submit that work with modifications,
    whether created in whole or in part by me, under the same open source
    license (unless I am permitted to submit under a different license), as
    indicated in the file; or
(c) The contribution was provided directly to me by some other person who
    certified (a), (b) or (c) and I have not modified it.
(d) I understand and agree that this project and the contribution are public and
    that a record of the contribution (including all personal information I
    submit with it, including my sign-off) is maintained indefinitely and may be
    redistributed consistent with this project or the open source license(s)
    involved.
```

## Development

```bash
pip install -r requirements.txt
python -m pytest          # run the test suite
python run.py             # run locally (needs a config.json; see config.example.json)
```

- Keep new behaviour covered by tests in `tests/`.
- Match the style and comment density of the surrounding code.
- Run the full test suite before opening a PR.

## Reporting bugs / requesting features

Open an issue with clear steps to reproduce (for bugs) or the problem you're
trying to solve (for features). Logs from the dashboard **Console** are helpful.
