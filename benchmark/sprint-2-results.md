# Sprint 2 Benchmark Results

**Project:** url-shortener
**Date:** 2026-06-03

## Summary

| Metric | Baseline (plain Claude) | Studio |
|--------|------------------------|--------|
| Duration | 44.7s | 3482.4s |
| Cost | $0.2183 | $11.4417 |
| Test coverage | 0.0% | 95.0% |
| Cyclomatic complexity | 7.0 | 3.0 |
| Duplication % | 33.0% | 31.9% |
| Friction items found | 1 | 20 |
| Friction items resolved | 0 | 18 |
| Design revisions | 0 | 7 |

## Studio wins
- coverage
- complexity
- coupling
- duplication
- design_feedback_loop

## Errors
Studio: none

## Event log (DoD proof — three loops + both human gates)

```
session_id = 4250338e-b617-4f1a-9f3e-dfcae03213ff

seq | event_type
--- | ----------
  1 | session.created
  2 | agent.started
  3 | agent.llm_call
  4 | agent.llm_response
  5 | ai.feedback_recorded
  6 | design.revised
  7 | agent.started
  8 | agent.llm_call
  9 | agent.llm_response
 10 | ai.feedback_recorded
 11 | agent.completed
 12 | slice.started
 13 | agent.started
 14 | agent.llm_call
 15 | agent.llm_response
 16 | ai.feedback_recorded
 17 | design_friction.reported
 18 | git.committed
 19 | agent.completed
 20 | slice.built
 21 | agent.started
 22 | agent.llm_call
 23 | agent.llm_response
 24 | ai.feedback_recorded
 25 | design.revised
 26 | agent.started
 27 | agent.llm_call
 28 | agent.llm_response
 29 | ai.feedback_recorded
 30 | agent.completed
 31 | slice.started
 32 | agent.started
 33 | agent.llm_call
 34 | agent.llm_response
 35 | ai.feedback_recorded
 36 | design_friction.reported
 37 | agent.completed
 38 | slice.built
 39 | verification.result
 40 | slice.verified
 41 | skeleton.validated
 42 | human.checkpoint
 43 | human.decision
 44 | agent.started
 45 | agent.llm_call
 46 | agent.llm_response
 47 | ai.feedback_recorded
 48 | agent.completed
 49 | agent.started
 50 | agent.llm_call
 51 | agent.llm_response
 52 | ai.feedback_recorded
 53 | design_friction.reported
 54 | agent.completed
 55 | agent.started
 56 | agent.llm_call
 57 | agent.llm_response
 58 | ai.feedback_recorded
 59 | design.revised
 60 | agent.started
 61 | agent.llm_call
 62 | agent.llm_response
 63 | ai.feedback_recorded
 64 | design_friction.reported
 65 | agent.completed
 66 | verification.result
 67 | agent.started
 68 | agent.llm_call
 69 | agent.llm_response
 70 | ai.feedback_recorded
 71 | agent.completed
 72 | agent.started
 73 | agent.llm_call
 74 | agent.llm_response
 75 | ai.feedback_recorded
 76 | reviewer.evaluated
 77 | agent.completed
 78 | agent.started
 79 | agent.llm_call
 80 | agent.llm_response
 81 | ai.feedback_recorded
 82 | design_friction.reported
 83 | agent.completed
 84 | verification.result
 85 | agent.started
 86 | agent.llm_call
 87 | agent.llm_response
 88 | ai.feedback_recorded
 89 | agent.completed
 90 | agent.started
 91 | agent.llm_call
 92 | agent.llm_response
 93 | ai.feedback_recorded
 94 | reviewer.evaluated
 95 | agent.completed
 96 | agent.started
 97 | agent.llm_call
 98 | agent.llm_response
 99 | ai.feedback_recorded
100 | design_friction.reported
101 | agent.completed
102 | agent.started
103 | agent.llm_call
104 | agent.llm_response
105 | ai.feedback_recorded
106 | design.revised
107 | agent.started
108 | agent.llm_call
109 | agent.llm_response
110 | ai.feedback_recorded
111 | design_friction.reported
112 | agent.completed
113 | verification.result
114 | agent.started
115 | agent.llm_call
116 | agent.llm_response
117 | ai.feedback_recorded
118 | agent.completed
119 | agent.started
120 | agent.llm_call
121 | agent.llm_response
122 | ai.feedback_recorded
123 | reviewer.evaluated
124 | agent.completed
125 | agent.started
126 | agent.llm_call
127 | agent.llm_response
128 | ai.feedback_recorded
129 | design_friction.reported
130 | agent.completed
131 | verification.result
132 | agent.started
133 | agent.llm_call
134 | agent.llm_response
135 | ai.feedback_recorded
136 | agent.completed
137 | agent.started
138 | agent.llm_call
139 | agent.llm_response
140 | ai.feedback_recorded
141 | reviewer.evaluated
142 | agent.completed
143 | agent.started
144 | agent.llm_call
145 | agent.llm_response
146 | ai.feedback_recorded
147 | design_friction.reported
148 | design_friction.reported
149 | design_friction.reported
150 | design_friction.reported
151 | agent.completed
152 | agent.started
153 | agent.llm_call
154 | agent.llm_response
155 | ai.feedback_recorded
156 | design.revised
157 | agent.started
158 | agent.llm_call
159 | agent.llm_response
160 | ai.feedback_recorded
161 | design_friction.reported
162 | agent.completed
163 | verification.result
164 | agent.started
165 | agent.llm_call
166 | agent.llm_response
167 | ai.feedback_recorded
168 | agent.completed
169 | agent.started
170 | agent.llm_call
171 | agent.llm_response
172 | ai.feedback_recorded
173 | reviewer.evaluated
174 | agent.completed
175 | agent.started
176 | agent.llm_call
177 | agent.llm_response
178 | ai.feedback_recorded
179 | design_friction.reported
180 | agent.completed
181 | verification.result
182 | agent.started
183 | agent.llm_call
184 | agent.llm_response
185 | ai.feedback_recorded
186 | agent.completed
187 | agent.started
188 | agent.llm_call
189 | agent.llm_response
190 | ai.feedback_recorded
191 | reviewer.evaluated
192 | agent.completed
193 | agent.started
194 | agent.llm_call
195 | agent.llm_response
196 | ai.feedback_recorded
197 | design_friction.reported
198 | agent.completed
199 | agent.started
200 | agent.llm_call
201 | agent.llm_response
202 | ai.feedback_recorded
203 | design.revised
204 | agent.started
205 | agent.llm_call
206 | agent.llm_response
207 | ai.feedback_recorded
208 | design_friction.reported
209 | design_friction.reported
210 | design_friction.reported
211 | agent.completed
212 | verification.result
213 | agent.started
214 | agent.llm_call
215 | agent.llm_response
216 | ai.feedback_recorded
217 | agent.completed
218 | agent.started
219 | agent.llm_call
220 | agent.llm_response
221 | ai.feedback_recorded
222 | design.revised
223 | agent.started
224 | agent.llm_call
225 | agent.llm_response
226 | ai.feedback_recorded
227 | design_friction.reported
228 | agent.completed
229 | verification.result
230 | agent.started
231 | agent.llm_call
232 | agent.llm_response
233 | ai.feedback_recorded
234 | agent.completed
235 | agent.started
236 | agent.llm_call
237 | agent.llm_response
238 | ai.feedback_recorded
239 | reviewer.evaluated
240 | agent.completed
241 | agent.started
242 | agent.llm_call
243 | agent.llm_response
244 | ai.feedback_recorded
245 | design_friction.reported
246 | agent.completed
247 | verification.result
248 | agent.started
249 | agent.llm_call
250 | agent.llm_response
251 | ai.feedback_recorded
252 | agent.completed
253 | agent.started
254 | agent.llm_call
255 | agent.llm_response
256 | ai.feedback_recorded
257 | reviewer.evaluated
258 | agent.completed
259 | human.checkpoint
260 | human.decision
261 | session.completed
```
