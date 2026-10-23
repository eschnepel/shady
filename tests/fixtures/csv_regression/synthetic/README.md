Developer-written fixtures that test the test system — see `../README.md`.

| File | `expected` | Proves |
| -- | -- | -- |
| `plain_string_elapsed_pass.csv` | *(absent → PASS)* | a real export replays cleanly; the default is PASS |
| `weather_tier_explicit_pass.csv` | `PASS` | the temperature branch replays; the explicit column is ignored by the comparison |
| `future_slot_blank_actuals_pass.csv` | *(absent → PASS)* | a not-yet-elapsed slot (blank `pv_selected`/`accuracy`) replays |
| `tampered_weight_fail.csv` | `FAIL` | a wrong `combined_weight` is caught |
| `tampered_accuracy_fail.csv` | `FAIL` | a wrong `accuracy` is caught |
| `unregistered_mode_fail.csv` | `FAIL` | an unknown `diagnostic_mode` is rejected |
| `clipping_excludes_sample_pass.csv` | *(absent → PASS)* | `converter_limit_w` really excludes a clipped training sample |
| `derating_weather_active_pass.csv` | *(absent → PASS)* | weather-tier derating (`coefficient_per_c`, `rated_dc_capacity_wp`) is recomputed forward and in reverse |
| `provider_already_corrects_pass.csv` | *(absent → PASS)* | `provider_already_corrects=true` skips both sides of the derating |
| `tampered_pv_corrected_fail.csv` | `FAIL` | a wrong `pv_corrected` is caught (formerly echoed) |
| `tampered_predicted_fail.csv` | `FAIL` | a wrong `predicted` is caught (formerly echoed) |
| `tampered_coefficient_fail.csv` | `FAIL` | a wrong fit scalar in `# metadata` is caught (formerly echoed) |

Exported from the scenarios in `tests/diagnostics/test_compare_regressions.py`
(`TestExportReplayRoundTrip`'s setups), then serialised with
`DiagnosticMode._write_csv_sections`.
