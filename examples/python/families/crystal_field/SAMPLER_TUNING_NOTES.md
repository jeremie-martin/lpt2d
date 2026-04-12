# Crystal Field Sampler Tuning Notes

These notes summarize the first measured free-sampler study from
`renders/families/crystal_field/studies/measured_1m_seed0.jsonl`.
The run was stopped at 312,573 probe rows and still included the old glass
outcome. Treat the numbers as guidance for the next no-glass study, not as
final tuned ranges.

## Big Picture

The measured pass rate was about 0.507% overall. Excluding glass conceptually
raises the useful non-glass pass rate to roughly 0.631%.

Most rejections were caused by measured light-radius gates, not by brightness:

| First rejection reason | Share of rejections |
| --- | ---: |
| `moving_radius_min` | 46.1% |
| `moving_radius_max` | 32.3% |
| `ambient_radius_min` | 9.7% |
| `moving_to_ambient_radius_ratio` | 6.6% |
| `ambient_radius_max` | 2.5% |
| brightness too high/low combined | about 1.3% |

Because the reason is the first failed gate, later brightness failures can be
hidden by earlier radius failures. Even with that caveat, the primary sampler
bottleneck is getting moving and ambient light radii into the accepted bands.

## Outcome Notes

Glass was effectively dead in this study: 6 accepted out of 62,573, or about
0.0096%. Temporarily disabling it while tuning the four non-glass outcomes was
the right choice.

Approximate pass rates by outcome:

| Outcome | Pass rate |
| --- | ---: |
| `colored_diffuse` | 0.827% |
| `brushed_metal` | 0.792% |
| `gray_diffuse` | 0.670% |
| `black_diffuse` | 0.234% |
| `glass` | 0.0096% |

Black diffuse fails `moving_radius_max` especially often, so it likely wants
lower moving intensity than colored diffuse and brushed metal.

## Actionable Tuning Leads

Exposure has a clear sweet spot. Overall, the useful range is around
`-5.6 .. -3.8`, with the strongest global bins near `-5.6 .. -4.4`.
Very dark exposure is nearly useless: `-8.0 .. -7.39` produced about 0.016%
pass rate.

Outcome-specific exposure signal:

| Outcome | Best observed exposure region |
| --- | --- |
| `black_diffuse` | about `-5.6 .. -5.0` |
| `gray_diffuse` | about `-5.6 .. -5.0` |
| `brushed_metal` | about `-5.0 .. -4.4` |
| `colored_diffuse` | about `-4.4 .. -3.8` |

Ambient intensity should not stay uniform over the full `0.05 .. 1.2` range.
The best global area is roughly `0.51 .. 0.74`, especially
`0.625 .. 0.740`. Very low ambient intensity is bad, and the highest ambient
intensity bins degrade again.

Exposure and ambient intensity should probably be sampled together. The best
interaction cells were around 2.3% to 2.4% pass rate, roughly 4.5x the overall
baseline:

| Exposure | Ambient intensity |
| --- | --- |
| `-5.0 .. -4.25` | `0.48 .. 0.77` |
| `-4.25 .. -3.50` | `0.34 .. 0.48` |
| `-5.74 .. -5.00` | `0.63 .. 0.77` |

Moving intensity should avoid the very low end. Globally, `0.69 .. 1.5` was
much better than `0.15 .. 0.42`, but black diffuse appears to prefer a lower
midrange around `0.55 .. 0.69`.

Gamma should avoid the very low range. The useful area is more like
`1.2 .. 1.9`; colored diffuse especially liked higher gamma around
`1.78 .. 1.92`.

White point had weaker signal than exposure, gamma, and intensity. The lowest
range, `0.25 .. 0.37`, was the worst global bin, but the data does not yet
justify a narrow white-point policy.

Colored ambient is visually useful but statistically harder. In this study,
white ambient passed at about 0.683%, while RGB colored ambient passed at
about 0.296%. For RGB ambient, high white mix looked worse; the better bins
were closer to `0.30 .. 0.35` than `0.55 .. 0.75`.

## Target Probe Metric Bands

These are measured outputs, not direct sampler inputs, but they describe what
the current probe thresholds tend to accept:

| Metric | Useful observed band |
| --- | --- |
| `metric_mean` | about `100 .. 135` |
| `metric_moving_radius_mean` | about `0.012 .. 0.023` |
| `metric_ambient_radius_mean` | about `0.008 .. 0.021` |
| `metric_contrast_spread` | about `69 .. 135` |
| `metric_mean_saturation` | about `0.45 .. 0.55`, bad above `0.66` |

## Refactor Direction

Do not move ranges into constants just for neatness. The useful cleanup is to
make the sampling policy explicit, named, inspectable, and condition-aware.

Keep `Params` as the saved/renderable configuration. Keep material generation
mostly as normal Python functions. Pull the tunable sampling policy into a
small set of plain Python policy objects covering:

- active outcome weights
- moving and ambient light intensity ranges
- light topology weights
- look ranges
- optional/fixed cases such as temperature and chromatic aberration
- complementary ambient color jitter and white mix

Maintain broad exploratory sampling until a no-glass measured dataset gives
cleaner evidence. After that, introduce a tuned policy as a separate change.
