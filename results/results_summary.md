# HTI Dark Patterns -- auto-generated results summary

_Generated from 13 file(s); N = 9 participants._ Numbers below are computed directly from the raw event logs.
- **Data-shift screen:** 13 complete participants checked; 4 flagged as shifted; 0 participant(s) had reload/crash resumes and 8 had ai_error retries (kept; see `s0_shift_detection.csv`).
  - DROPPED PMUMQER6JZK: recall/div-attn accuracy blank in export (older client build) (exported claims A/R/T 3.0/7.0/1.0 vs replay 3/7/1).
  - DROPPED PMUMQG3HEY4: recall/div-attn accuracy blank in export (older client build) (exported claims A/R/T 4.0/8.0/0.0 vs replay 4/8/0).
  - DROPPED PMUMQHFT3NI: recall/div-attn accuracy blank in export (older client build) (exported claims A/R/T 2.0/8.0/1.0 vs replay 2/8/1).
  - DROPPED PMUMQR075XD: recall/div-attn accuracy blank in export (older client build) (exported claims A/R/T 2.0/10.0/0.0 vs replay 2/10/0).

## 0. Sample, design integrity and data quality

- Participants in files: **N = 9**; participants with all 12 trials submitted: 5; with a recognition test: 8.
- Age: M = 19.7, SD = 1.2, range 18-22. Gender: {'Male': 6, 'Female': 3}. Education: {"Undergraduate (Bachelor's)": 5, 'High school / Secondary': 3, "Postgraduate (Master's)": 1}. Domain: {'STEM (Science, Technology, Engineering, Maths)': 9}.
- AI experience (1-5): M = 4.33; critical-evaluation self-rating (1-5): M = 3.33; AI-planning familiarity (1-5): M = 3.33; emotionality (mean of 4 items): M = 3.08.
- Trials per load condition: {'LowLoad': 44, 'HighLoad': 40}. Task-order counts: {'A_Workload|C_NonAcademicLife|B_DegreeRequirements': 2, 'B_DegreeRequirements|A_Workload|C_NonAcademicLife': 2, 'B_DegreeRequirements|C_NonAcademicLife|A_Workload': 2, 'C_NonAcademicLife|B_DegreeRequirements|A_Workload': 2, 'C_NonAcademicLife|A_Workload|B_DegreeRequirements': 1}.
- Load sequences used (per task block): {'HighLoad|LowLoad|HighLoad|LowLoad': 6, 'HighLoad|LowLoad|LowLoad|HighLoad': 6, 'LowLoad|HighLoad|HighLoad|LowLoad': 6, 'LowLoad|LowLoad|HighLoad|HighLoad': 6, 'LowLoad|HighLoad|LowLoad|HighLoad': 3}.
- Dark-turn delivery: 83 of 84 trials contain a dark turn; trials with exactly one: 83; tactic verified by the platform's LLM check: 76 (92%); downgraded: 0; fallback target used: 0; delivered on proactive (not user-initiated) turn: 0.
- Dark turn landed on the participant's 1st reply in 60% of trials (deployed `main.py` targets 60/40 -- the old design notes say 70/30; report 60/40).
- **Manipulation validity (costly target):** platform's own check says the target was genuinely costly to follow at delivery in 100% of dark turns; by a stricter plan-quality-only test 73% (the remainder are costly only through the hours/credit tie-break, i.e. a *small* cost). Report both, and use `q_cost_of_following` as severity.
- Tactic coverage (n trials): Excessive Flattery [A]=8; Opaque Reasoning Processes [A]=8; Simulated Authority [A]=3; Sycophantic Agreement [A]=3; Unprompted Intimacy Probing [A]=6; Behavioral Profiling via Dialogue [B]=7; Ideological Steering [B]=6; Opaque Training Data Sources [B]=7; Simulated Authority [B]=3; Sycophantic Agreement [B]=3; Brand Favoritism [C]=7; Interaction Padding [C]=8; Simulated Authority [C]=4; Simulated Emotional & Sexual Intimacy (bounded, non-romantic) [C]=7; Sycophantic Agreement [C]=3
- Trial-level quality flags: {'timed_out': 9, 'tactic_unverified': 3, 'no_dark_turn': 1}; timed-out trials: 9/84 ({'HighLoad': 0.225, 'LowLoad': 0.0}).
- **Restarted segments** (trial_started fired more than once = page refresh/reload): 0 trials in 0 participants. Only the last attempt is analysed. The platform's own Claims_* / Corrections_* export counts a restart as an extra segment, which shifts its task assignment for the rest of the session -- if a participant listed here also appears in the cross-check mismatches below, the export is the one that is wrong.
- **Export cross-check:** recomputed 81 platform summary values from raw events; mismatches: 5. -> PMUL4HNZO6H:Turns_Elapsed exported 98.0 vs 93.0; PMUMDQ3OED4:Turns_Elapsed exported 81.0 vs 66.0; PMUMDROVABW:Turns_Elapsed exported 59.0 vs 47.0; PMUMDXHW1IL:Claims_Rejected exported 8.0 vs 7.0; PMUMDXHW1IL:Turns_Elapsed exported 89.0 vs 63.0
- **Own outcome coding vs the platform's scoring rule (replayed):** 106 trials scored by both, 0 disagree; 1 trials scored by only one of them. Disagreements (participant, trial, category: platform vs own; target hours/presence before -> at first submit): ; only-one-scored: PMUMDXHW1IL t12

## 1. Manipulation checks (was High load actually higher load?)

- Raw NASA-TLX composite (1-7): Low M = 2.24, High M = 3.44; mean within-person diff = +1.19 [+0.71, +1.64] (bootstrap 95% CI), paired t(8) = 4.58, p = .002, Wilcoxon p = .012, dz = 1.53; 8 of 9 participants higher under High load, 1 lower, 0 tied.
- Mental demand: Low M = 2.31, High M = 3.61; mean within-person diff = +1.30 [+0.77, +1.78] (bootstrap 95% CI), paired t(8) = 4.81, p = .001, Wilcoxon p = .008, dz = 1.60; 8 of 9 participants higher under High load, 0 lower, 1 tied.
- Effort: Low M = 2.37, High M = 3.70; mean within-person diff = +1.33 [+0.78, +1.94] (bootstrap 95% CI), paired t(8) = 4.15, p = .003, Wilcoxon p = .008, dz = 1.38; 8 of 9 participants higher under High load, 0 lower, 1 tied.
- Temporal demand: Low M = 1.89, High M = 3.62; mean within-person diff = +1.73 [+0.74, +2.56] (bootstrap 95% CI), paired t(8) = 3.45, p = .009, Wilcoxon p = .020, dz = 1.15; 8 of 9 participants higher under High load, 1 lower, 0 tied.
- Frustration: Low M = 2.35, High M = 3.19; mean within-person diff = +0.83 [-0.15, +1.67] (bootstrap 95% CI), paired t(8) = 1.72, p = .123, Wilcoxon p = .164, dz = 0.57; 7 of 9 participants higher under High load, 2 lower, 0 tied.
- Self-rated performance: Low M = 4.99, High M = 4.21; mean within-person diff = -0.77 [-1.44, -0.03] (bootstrap 95% CI), paired t(8) = -2.07, p = .073, Wilcoxon p = .117, dz = -0.69; 1 of 9 participants higher under High load, 7 lower, 1 tied.
- Notifications per trial: Low M = 1.41, High M = 4.23; mean within-person diff = +2.82 [+2.52, +3.13] (bootstrap 95% CI), paired t(8) = 16.99, p < .001, Wilcoxon p = .004, dz = 5.66; 9 of 9 participants higher under High load, 0 lower, 0 tied.
- Notification recall-check accuracy: Low M = 0.93, High M = 0.79; mean within-person diff = -0.14 [-0.25, -0.06] (bootstrap 95% CI), paired t(8) = -2.67, p = .028, Wilcoxon p = .020, dz = -0.89; 1 of 9 participants higher under High load, 8 lower, 0 tied.
- Trial duration (s): Low M = 163.07, High M = 192.66; mean within-person diff = +29.59 [-9.10, +66.56] (bootstrap 95% CI), paired t(8) = 1.44, p = .188, Wilcoxon p = .203, dz = 0.48; 6 of 9 participants higher under High load, 3 lower, 0 tied.
- User messages per trial: Low M = 5.19, High M = 5.17; mean within-person diff = -0.02 [-1.26, +1.35] (bootstrap 95% CI), paired t(8) = -0.03, p = .978, Wilcoxon p = .910, dz = -0.01; 4 of 9 participants higher under High load, 5 lower, 0 tied.
- Divided-attention task (High load only): pooled hit rate = 42.2%; false alarms = 38 total; per-participant hit rate M = 41.1% (SD 14.2%). Low hit-rates indicate the secondary task was demanding (or that the digit stream is too fast -- see participant feedback).
- LMM rtlx ~ load + timed + trial position (random intercept for participant): High load: b = 1.25, 95% CI [0.87, 1.64], p < .001; timed segment: b = 0.25, 95% CI [-0.16, 0.65], p = .233
- LMM tlx_mental ~ load + timed + trial position (random intercept for participant): High load: b = 1.38, 95% CI [0.87, 1.88], p < .001; timed segment: b = 0.13, 95% CI [-0.40, 0.66], p = .624
- **Confound to disclose:** on timed segments (3 and 4) High load also cut the time limit by 20% (A/B 3:12 vs 4:00; C 2:24 vs 3:00). Timed-out: High 39% vs Low 0%. Run the load effect on untimed segments (1-2) only as a robustness check (see s2 sensitivity table).

## 2. PRIMARY: does cognitive load change compliance with the costly manipulative recommendation?

Analysis set: 80 trials from 9 participants (one verified dark turn per trial; unverified dark turns excluded, as in the recognition test).
- HighLoad: accepted the costly recommendation in 10/38 trials = 26.3% (Wilson 95% CI 15.0%-42.0%).
- LowLoad: accepted the costly recommendation in 16/42 trials = 38.1% (Wilson 95% CI 25.0%-53.2%).
- Outcome counts: {'accepted': 26, 'rejected': 51, 'transient': 3}. (Transient = target briefly followed then reverted; counted as *not accepted* in the primary DV and as uptake in the sensitivity DV.)
- **Participant-level paired test (recommended headline):** P(accept): Low M = 0.39, High M = 0.32; mean within-person diff = -0.06 [-0.38, +0.31] (bootstrap 95% CI), paired t(7) = -0.34, p = .747, Wilcoxon p = .562, dz = -0.12; 2 of 8 participants higher under High load, 4 lower, 2 tied.
  Sign-flip randomisation p = 0.875; exact sign test p = .688.
- Within-participant label-permutation test (10,000 shuffles of High/Low labels inside each person): observed mean diff = -0.062, p = .612.
- GEE logit (exchangeable, clustered on participant), accepted ~ load: High vs Low: OR = 0.58, 95% CI [0.19, 1.76], p = .339
- Adjusted for task, timed segment, trial position: High vs Low: OR = 0.49, 95% CI [0.14, 1.63], p = .243
- Load x task interaction terms: high:C(cat)[T.B]: OR = 0.66, 95% CI [0.06, 7.87], p = .745; high:C(cat)[T.C]: OR = 0.71, 95% CI [0.16, 3.19], p = .651
- **Heterogeneity:** {'more compliant under LOW': 4, 'no difference': 2, 'more compliant under HIGH': 2}. Participants whose compliance rose under High load: 2 of 8; mean compliance rate overall = 33.1%.
- SD of individual High-Low differences = 0.527; expected under 'no true individual differences' (binomial noise around each person's own mean) = 0.305 [95% 0.146, 0.488] -> more heterogeneity than chance.
- Dose-response with *perceived* load (raw TLX split into within-person and between-person parts): within-person +1 TLX point: OR = 0.85, 95% CI [0.51, 1.40], p = .516; between-person +1 TLX point: OR = 1.20, 95% CI [0.68, 2.11], p = .534
- Adding cost severity (B/C turns with quality penalty >= 1): High: OR = 0.55, 95% CI [0.14, 2.17], p = .396; severe cost: OR = 0.56, 95% CI [0.20, 1.57], p = .267
- Moderation of the load effect by individual differences (interaction OR per +1 SD; Holm-adjusted): critical_ability: OR = 1.72, p = 0.326 (Holm 1.000); ai_experience: OR = 1.34, p = 0.601 (Holm 1.000); ai_planning_familiarity: OR = 0.91, p = 0.865 (Holm 1.000); emotionality: OR = 0.95, p = 0.946 (Holm 1.000)
- Sensitivity table saved (`s2_sensitivity.csv`); every row reports High-Low difference, participant-level paired p and GEE OR.

## 3. Secondary behaviour: corrections, verification, effort and reading time

- corrections: Low 2.50 vs High 2.80 (diff +0.30, p = .425, Holm p = 1.000)
- n_removes: Low 1.60 vs High 1.81 (diff +0.21, p = .311, Holm p = 1.000)
- n_facts_revealed: Low 2.40 vs High 2.19 (diff -0.21, p = .612, Holm p = 1.000)
- prop_facts_revealed: Low 0.70 vs High 0.73 (diff +0.03, p = .480, Holm p = 1.000)
- target_fact_before_dark: Low 0.21 vs High 0.10 (diff -0.10, p = .305, Holm p = 1.000)
- target_fact_after_dark: Low 0.24 vs High 0.26 (diff +0.02, p = .732, Holm p = 1.000)
- asked_target_before_dark: Low 0.11 vs High 0.11 (diff +0.00, p = 1.000, Holm p = 1.000)
- asked_target_after_dark: Low 0.31 vs High 0.33 (diff +0.02, p = .812, Holm p = 1.000)
- n_user_before_dark: Low 1.43 vs High 1.29 (diff -0.14, p = .148, Holm p = 1.000)
- duration_s: Low 159.75 vs High 187.91 (diff +28.15, p = .159, Holm p = 1.000)
- final_pct_scored: Low 55.14 vs High 57.92 (diff +2.78, p = .791, Holm p = 1.000)
- submit_attempts: Low 1.47 vs High 1.27 (diff -0.20, p = .303, Holm p = 1.000)
- latency_after_dark_s: Low 26.10 vs High 28.93 (diff +2.83, p = .433, Holm p = 1.000)
- latency_after_neutral_s: Low 19.99 vs High 24.87 (diff +4.88, p = .122, Holm p = 1.000)
- dwell_dark_rel: Low 1.20 vs High 1.33 (diff +0.14, p = .052, Holm p = .993)
- msg_words_mean: Low 5.57 vs High 4.92 (diff -0.66, p = .068, Holm p = 1.000)
- msg_wpm_mean: Low 44.50 vs High 44.72 (diff +0.22, p = .963, Holm p = 1.000)
- msg_pause_mean_s: Low 18.05 vs High 22.78 (diff +4.73, p = .024, Holm p = .470)
- msg_backspaces_mean: Low 2.12 vs High 1.17 (diff -0.95, p = .061, Holm p = 1.000)
- q_final_raw: Low 0.00 vs High -21.04 (diff -21.04, p = .347, Holm p = 1.000)
- Reading/hesitation proxy: extra latency before the next user message after the dark turn vs after neutral AI turns (dark - neutral seconds): diff-of-latency: Low M = 6.01, High M = 4.65; mean within-person diff = -1.36 [-8.45, +6.28] (bootstrap 95% CI), paired t(7) = -0.33, p = .750, Wilcoxon p = .844, dz = -0.12; 3 of 8 participants higher under High load, 5 lower, 0 tied.
- **ELM central-route check.** Load -> asking about the flagged item after the dark turn: high: OR = 1.32, 95% CI [0.69, 2.53], p = .404. Asking -> accepting (controlling load): asked_target_after_dark: OR = 6.16, 95% CI [2.59, 14.68], p < .001. Load -> revealing a locked fact about the target: high: OR = 1.69, 95% CI [0.62, 4.59], p = .301. Revealing -> accepting: target_fact_after_dark: OR = 1.40, 95% CI [0.37, 5.34], p = .619.
  Indirect effect (log-odds scale, load -> asks about target -> accepts): +0.571, participant-bootstrap 95% CI [-0.572, +2.001] (exploratory).
- Objective cost of compliance (means by accepted=0/1): {0.0: {'final_pct_scored': 61.48, 'q_final_raw': -0.06, 'duration_s': 167.41, 'corrections': 2.8}, 1.0: {'final_pct_scored': 39.19, 'q_final_raw': -38.73, 'duration_s': 199.54, 'corrections': 2.81}}

## 3A. Category A: how and when the under-allocated target was corrected (accepted/rejected is at ceiling for A)

- 28 Category A trials from 8 participants. Target hours were raised after the dark turn in 100% of them (High 100%, Low 100%); the 28 corrected trials are analysed below. Caution: not every A tactic makes a false claim (flattery, intimacy probing and authority can wrap the *correct* number), so speed of correction is a measure of how quickly people act on the truth, not of how far they trusted a lie.
- Seconds from dark turn to first raise of the target: Low M = 42.95, High M = 40.19; mean within-person diff = -2.77 [-46.64, +37.36] (bootstrap 95% CI), paired t(6) = -0.12, p = .911, Wilcoxon p = .812, dz = -0.04; 4 of 7 participants higher under High load, 3 lower, 0 tied.
- User messages until the target was raised: Low M = 1.43, High M = 1.50; mean within-person diff = +0.07 [-1.36, +1.50] (bootstrap 95% CI), paired t(6) = 0.09, p = .930, Wilcoxon p = .984, dz = 0.03; 4 of 7 participants higher under High load, 3 lower, 0 tied.
- Share of fixes where the participant typed the number: Low M = 0.93, High M = 0.86; mean within-person diff = -0.07 [-0.21, +0.00] (bootstrap 95% CI), paired t(6) = -1.00, p = .356, Wilcoxon p = 1.000, dz = -0.38; 0 of 7 participants higher under High load, 1 lower, 6 tied.
- Share where the AI had already disclosed the true value: Low M = 0.43, High M = 0.71; mean within-person diff = +0.29 [-0.07, +0.57] (bootstrap 95% CI), paired t(6) = 1.55, p = .172, Wilcoxon p = .312, dz = 0.59; 4 of 7 participants higher under High load, 1 lower, 2 tied.
- Share where the participant asked about the target before fixing it: Low M = 0.00, High M = 0.07; mean within-person diff = +0.07 [+0.00, +0.21] (bootstrap 95% CI), paired t(6) = 1.00, p = .356, Wilcoxon p = 1.000, dz = 0.38; 1 of 7 participants higher under High load, 0 lower, 6 tied.
- LMM log(1 + seconds to fix) ~ load + timed (random intercept for participant): High load (b is on the log scale; exp(b) = time ratio): b = 0.85, 95% CI [-0.64, 2.35], p = .263
- Median seconds to fix by tactic: Excessive Flattery = 40.0 s (n = 8); Opaque Reasoning Processes = 23.2 s (n = 8); Simulated Authority = 62.9 s (n = 3); Sycophantic Agreement = 45.2 s (n = 3); Unprompted Intimacy Probing = 0.0 s (n = 6)

## 4. Recognition of manipulation (signal detection) and its link to resisting

- Pooled: hit rate (dark flagged as manipulative) = 53.1% (32 dark items); false-alarm rate (neutral rewrite flagged) = 12.9% (31 neutral items); d' = 1.15, criterion c = 0.50.
- Per-participant d' M = 0.89 (SD 1.18); 2 of 8 participants at or below chance (d' <= 0). Only ~10 items per person, so d' is coarse: report pooled/GEE estimates as primary.
  - excerpts from HighLoad trials: hit 35.7%, FA 5.6%, d' = 1.07, c = 0.88
  - excerpts from LowLoad trials: hit 66.7%, FA 23.1%, d' = 1.08, c = 0.13
- GEE logit: flagged ~ is_dark x load. Detection (dark vs neutral): OR = 7.01, 95% CI [1.13, 43.65], p = .037; is_dark x High load (does load impair discrimination?): OR = 1.38, 95% CI [0.05, 40.15], p = .853; High load main (bias): OR = 0.19, 95% CI [0.01, 3.17], p = .247
- d'(High) - d'(Low) = -0.01, participant-bootstrap 95% CI [-1.53, +1.37].
- Agreement rating (1-5) with the excerpt: dark vs neutral: b = -1.05, 95% CI [-2.17, 0.08], p = .067; dark x High load: b = 1.28, 95% CI [0.52, 2.05], p < .001
- **Awareness vs resistance** (dark excerpts, n = 32): accepted the costly advice in 41.2% of recognised turns (n = 17) vs 26.7% of unrecognised turns (n = 15). Aware-yet-complied: 7 trials = 41.2% of recognised turns.
  Fisher exact p = 0.472 (ignores clustering).
  GEE: recognised -> accepted: OR = 1.17, 95% CI [0.17, 7.88], p = .876; High load: OR = 0.30, 95% CI [0.03, 2.68], p = .280
  recognition x load: OR = 12.89, 95% CI [1.27, 130.63], p = .031
  Rated agreement with the dark excerpt vs having accepted it: Spearman rho = 0.01, p = .967.
- Participant level: hit_rate vs overall P(accept): Spearman rho = -0.43, p = .286 (n = 8).
- Participant level: dprime vs overall P(accept): Spearman rho = -0.43, p = .288 (n = 8).

## 5. Subjective reliance, trust and the introspection gap

- tlx_helpfulness: Low 2.51 vs High 2.60 (p = .839; Holm p = 1.000)
- tlx_trust: Low 2.37 vs High 2.52 (p = .727; Holm p = 1.000)
- tlx_persuasiveness: Low 2.27 vs High 2.40 (p = .780; Holm p = 1.000)
- tlx_independence: Low 3.85 vs High 3.70 (p = .562; Holm p = 1.000)
- tlx_performance: Low 4.99 vs High 4.21 (p = .073; Holm p = .363)
- tlx_trust ~ accepted + load + task: accepted the costly advice: b = 0.53, 95% CI [0.02, 1.04], p = .041
- tlx_helpfulness ~ accepted + load + task: accepted the costly advice: b = 0.35, 95% CI [-0.07, 0.77], p = .105
- tlx_persuasiveness ~ accepted + load + task: accepted the costly advice: b = 0.44, 95% CI [-0.06, 0.95], p = .085
- tlx_independence ~ accepted + load + task: accepted the costly advice: b = -0.29, 95% CI [-0.63, 0.05], p = .096
- Self-reported independence vs behavioural compliance: Spearman rho = -0.08 (p = .478); self-reported influence: rho = 0.11 (p = .354). Weak correlations = self-report does not track behavioural reliance.
- Introspection gap: among trials where the participant did follow the costly advice (n = 26), 23% rated themselves 5-7 on 'relied on own judgment' and 65% rated AI influence 1-3.
- Calibration: self-rated performance vs platform plan-quality %: rho = -0.01 (p = .947) (quality % rewards slack among passing plans, so treat as descriptive).

## 6. Which manipulative tactics work? (descriptive; cell sizes are small)

- [B] Simulated Authority: 3/3 = 100% [44%, 100%]
- [B] Sycophantic Agreement: 2/3 = 67% [21%, 94%]
- [C] Sycophantic Agreement: 2/3 = 67% [21%, 94%]
- [B] Ideological Steering: 3/6 = 50% [19%, 81%]
- [C] Interaction Padding: 4/8 = 50% [22%, 78%]
- [B] Behavioral Profiling via Dialogue: 3/7 = 43% [16%, 75%]
- [A] Simulated Authority: 1/3 = 33% [6%, 79%]
- [A] Sycophantic Agreement: 1/3 = 33% [6%, 79%]
- [C] Simulated Authority: 1/3 = 33% [6%, 79%]
- [A] Excessive Flattery: 2/7 = 29% [8%, 64%]
- [C] Brand Favoritism: 2/7 = 29% [8%, 64%]
- [A] Opaque Reasoning Processes: 1/7 = 14% [3%, 51%]
- [C] Simulated Emotional & Sexual Intimacy (bounded, non-romantic): 1/7 = 14% [3%, 51%]
- [A] Unprompted Intimacy Probing: 0/6 = 0% [0%, 39%]
- [B] Opaque Training Data Sources: 0/7 = 0% [0%, 35%]
- By taxonomy cluster: Content & Belief 53% (n=15); Decision & Outcome 44% (n=16); Engagement & Behavioral 32% (n=22); Privacy & Data Exploitation 23% (n=13); Transparency & Accountability 7% (n=14)
- By task direction (A: advice understates a need; B/C: advice pushes a harmful add/keep): harmful-add/keep 39%; understate-need 19%
- Omnibus test that tactics differ in compliance (chi-square-type statistic = 15.1; p from 2000 permutations of tactic labels within participant x task) p = .082. Tactic order was a fixed rotation, not random, so tactic is confounded with trial position/load within a task -- state this if you report it.
- Compliance by reply position (1st vs 2nd): {1.0: {'mean': 0.31, 'count': 48}, 2.0: {'mean': 0.34, 'count': 32}}

## 7. Order, learning and carry-over effects

- Compliance across the 12 trial positions: rho(position, rate) = 0.10, p = .769.
- GEE: trial position (per SD): OR = 1.02, 95% CI [0.52, 2.03], p = .951; High load, controlling for position: OR = 0.58, 95% CI [0.19, 1.78], p = .343
- By segment within task (1-2 untimed, 3-4 timed): {1: 0.4, 2: 0.17, 3: 0.21, 4: 0.56}; by task position (1st/2nd/3rd task): {1: 0.32, 2: 0.36, 3: 0.3}
- Carry-over (previous trial): previous trial accepted: OR = 2.42, 95% CI [1.20, 4.86], p = .013; previous trial High load: OR = 1.59, 95% CI [0.58, 4.34], p = .370

## 8. Individual differences

- 20 exploratory correlations saved to `s8_correlations.csv`; only report those that survive Holm correction as findings.
- Emotionality scale reliability (Cronbach's alpha, 4 items): 0.81.

## 9. Accountability-driven explanations (task-level justification + LLM reasoning score)

- 19 task-level justifications from 8 participants; LLM reasoning score (0-10): M = 5.16 (SD 2.24). Justification is collected once per task (after segment 4), so it cannot be split by load; it is analysed against how many of the task's 4 dark turns were accepted.
- Reasoning score vs # costly recommendations accepted in that task: rho = 0.16, p = .500.
- Justification length vs # accepted: rho = 0.10, p = .677.
- LMM reasoning_score ~ n_accepted + task: per additional accepted recommendation: b = -0.00, 95% CI [-1.20, 1.20], p = .996
- Language: 53% of justifications refer to the AI/its suggestions; 53% cite constraints/tradeoffs; only 0% contain manipulation-related vocabulary (regex screen -- confirm by manual coding).

## 10. Free text: demand characteristics, awareness, feedback (coding sheet exported)

- 39 free-text responses exported to `qualitative_coding_sheet.csv` with blank code columns for two coders (compute Cohen's kappa) -- codes: guessed true purpose / admitted reliance / noticed manipulation / complained about load task.
- Participant feedback mentioning the divided-attention or notification task (1 of 2 feedback comments) is direct evidence about load-manipulation validity/acceptability.
- Regex screen for manipulation vocabulary in the post-test reflections: 1 of 18. Demand-characteristics answers are collected *before* the debrief; code them first and run the primary model with/without participants who guessed the purpose.

## 11. Sensitivity / power

- Paired test on participant means with N = 9: 80%-power minimum detectable effect dz = 1.07.
- Paired test on participant means with N = 30: 80%-power minimum detectable effect dz = 0.53.
- Between-participant SD of overall compliance rate = 0.14; a large between-person share justifies the within-subject design and the clustered models.