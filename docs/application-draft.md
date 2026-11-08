# Startup Buildathon India 2026: Application Draft

Product: AI Relocation Agent, the first product of The New Guy in Town
Status: Draft for friend review on 12 November. Submit by 13 November 2026.
Source: every fact below comes from `docs/PRD.md`. Items marked **[TO FILL]** need real interview results.

---

## 1. The problem

When an IT employee moves to Hyderabad for a new job, they must choose a place to live without knowing the city. They do not know which areas are close to the office, what rent is fair, or which PGs are honest. Calling many PG owners takes time, and the rental agreement is hard to read before paying.

We think this is a serious problem, and we are testing that now.

- **[TO FILL]** of 5 recently moved people rated the problem as serious (our bar is at least 3 of 5).
- **[TO FILL]** One real quote from an interview, for the demo opening.
- **[TO FILL]** Typical time these people spent finding a place.

## 2. The solution

An AI agent that acts like a local friend. It knows the city, makes the calls for you, and reads the agreement carefully.

You enter your office address, monthly budget, arrival date, and food and commute needs. You get back a ranked shortlist with commute time, cost, call results and agreement risks.

Our success test: a new user goes from an office address to a shortlist of three PGs and one checked agreement in under 10 minutes.

## 3. The three features

1. **Area Advisor.** Ranks 3 to 5 Hyderabad areas using your office commute, rent range and needs. Commute times come from Google Maps at peak hour, not from the AI. Every rent range shows its source and date. The AI only explains the result.
2. **PG Caller.** Speaks with PG owners who agreed to take AI calls, in Telugu, Hindi or English. It saves rent, deposit, food, availability and rules in a comparison table. If an answer is unclear, the table says "not confirmed" instead of guessing. The agent always says it is an AI, and you approve every call before it starts.
3. **Agreement Checker.** Reads a PDF or photo of the rental agreement and explains risky clauses in simple language. Each risk points to the exact clause in the document. Every result says this is not legal advice.

## 4. The 3-minute demo

| Time | What judges see | What we say |
| --- | --- | --- |
| 0:00 to 0:30 | A real interview quote **[TO FILL]** | "Moving to a new city means choosing a home without knowing the city." |
| 0:30 to 1:00 | Enter office address and budget | Commute numbers come from Google Maps, and Gemini explains them |
| 1:00 to 1:50 | Staged owner conversation in Telugu, by browser microphone | "This owner agreed to this demo. The agent says that it is AI." |
| 1:50 to 2:20 | Comparison table fills in | Unclear answers stay "not confirmed" |
| 2:20 to 2:45 | Upload an agreement | Each risk points to the exact clause |
| 2:45 to 3:00 | Business and next step | Companies pay per relocating employee; rides and storage come later |

Honest note for judges: the demo uses seed data and a teammate acting as the owner, clearly described as staged. No real phone calls are made at the event. We have a recorded backup of the full demo.

## 5. Business model

We will test two ideas:

- **Companies pay per relocating employee.** This is our first choice. Companies can pay more easily than individual movers, and HR sees only usage counts, never an employee's personal data.
- **PGs pay for qualified leads.** PG owners get serious enquiries, without spam.

We have not set a price. We will set it after we know our cost per completed move plan (AI, phone and Maps costs) and have spoken with HR teams. **[TO FILL]** HR conversations held so far.

## 6. What's next

- **Now to 21 November:** Build the P0 features for the Buildathon demo. Collect 20 real PG details by phone or in person.
- **December 2026, private alpha:** 20 real movers and an owner web form. We move forward only if at least 3 of 5 interviewed movers rate the problem as serious.
- **January to March 2027, paid pilot:** 100 movers and real phone calls, but only after consent, telecom registration and legal review are done, and 20 PGs have given consent.
- **From April 2027, production:** Public in Hyderabad, then new cities, once security and tests pass and at least one customer pays.
- **Later roadmap:** A first-week plan, flat video inspection and asking locals; then luggage storage, short stays and shared commutes; then guides and weekend communities.

Dates after the Buildathon are proposed. They depend on legal review and customer demand.

### Risks we are upfront about

- India's rules on AI voice calls are the biggest production risk. We will confirm them with a telecom lawyer before any real calling.
- PG owners may refuse AI calls. We will test with 20 owners and offer WhatsApp or a web form instead.
- Telugu quality on real phone audio is unproven. We are testing it early.
- Rent data may be incomplete, so we will start with a few areas and verified PGs.

---

## Pitch deck outline (10 slides)

1. **Title:** The New Guy in Town: a local friend for anyone moving to Hyderabad.
2. **Problem:** You must choose a home in a city you do not know, and you have days to do it.
3. **Proof:** "[TO FILL]" real quote and **[TO FILL]** of 5 movers who called it a serious problem.
4. **Solution:** One AI agent that ranks areas, calls PGs and checks your agreement.
5. **Feature 1, Area Advisor:** Ranked areas with real peak-hour commute times from Google Maps.
6. **Feature 2, PG Caller:** Calls owners who agreed, in Telugu, Hindi or English, and fills a comparison table.
7. **Feature 3, Agreement Checker:** Every risky clause quoted from the document, with a not-legal-advice notice.
8. **Trust by design:** The agent says it is AI, you approve every call, owners can say stop at any time, and unknowns stay "not confirmed".
9. **Business model:** Companies pay per relocating employee, or PGs pay for qualified leads; price to be set after cost and HR talks.
10. **What's next:** Alpha with 20 movers in December, paid pilot in early 2027, then rides, storage and community.

---

## 5-person mover interview script

**Who to interview:** 5 people who recently moved to Hyderabad for an IT job. Aim for about 20 minutes each.

**Rules for the interviewer**
- Ask about what they did, not what they would do. Past behaviour is more reliable than opinions.
- Do not mention our product until the final section.
- Do not lead. Ask "How did you find a place?", not "Wasn't finding a place hard?"
- Write down their exact words. We may use one quote in the demo (ask permission).

### Questions

**A. Context (2 minutes)**
1. When did you move to Hyderabad, and where from?
2. Where is your office, and how long did you have before joining?

**B. What actually happened (6 minutes)**
3. Walk me through how you found a place to live. What did you do first?
4. How many places did you contact or visit? How long did the whole search take?
5. How did you decide which area to live in? What information did you use?
6. Did you speak with PG owners or brokers? What was that like, and in which language?

**C. Is this their main problem? (7 minutes)**
7. Of everything about moving, what was the single hardest part? (Do not offer choices. Let them name it.)
8. If you could fix one thing about that first month, what would it be?
9. On a scale of 1 to 5, how serious was the problem of choosing where to live? Why that number?
10. What did it cost you: money, days off work, a bad stay, a wrong choice? Give me one example.
11. Did you read the rental agreement before paying? Did anything in it surprise you later?
12. What did you try to solve it (friends, apps, brokers)? What was wrong with that?
13. Have you paid for any help with moving? How much, and who paid, you or your company?

**D. Reaction to the idea (4 minutes, only now)**
14. I will describe a tool in two sentences: it ranks areas by your commute, calls PGs for you and checks the agreement. What is your first reaction?
15. Which of the three parts, areas, calls or agreement, would you use first? Which would you skip?
16. How would you feel about an AI making the PG calls for you, if it said clearly that it is an AI?

**E. Close (1 minute)**
17. Who else recently moved to Hyderabad that I could talk to?
18. Can I quote you, without your name, in our application?

### How to read the answers

Counting toward "this is their main problem":
- They name housing or area choice on their own in Q7 or Q8, without being prompted.
- They gave a score of 4 or 5 in Q9.
- They describe a real cost in Q10 (time, money, a bad stay).
- They tried to solve it in Q12.

Warning signs:
- They only say it is a problem after hearing the idea in section D.
- They name a different main problem, such as a job, visa or food. If so, record it for the roadmap.
- Q9 is a 3 or lower and they have no cost story.

Gate from the PRD: at least 3 of 5 must rate the problem as serious before we move from demo to alpha.

### Results sheet (fill after each interview)

| # | Role and moved when | Named housing as hardest part (Q7/Q8) | Score (Q9) | Cost story (Q10) | Wants AI calls (Q16) | Quote |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | [TO FILL] | [TO FILL] | [TO FILL] | [TO FILL] | [TO FILL] | [TO FILL] |
| 2 | [TO FILL] | [TO FILL] | [TO FILL] | [TO FILL] | [TO FILL] | [TO FILL] |
| 3 | [TO FILL] | [TO FILL] | [TO FILL] | [TO FILL] | [TO FILL] | [TO FILL] |
| 4 | [TO FILL] | [TO FILL] | [TO FILL] | [TO FILL] | [TO FILL] | [TO FILL] |
| 5 | [TO FILL] | [TO FILL] | [TO FILL] | [TO FILL] | [TO FILL] | [TO FILL] |

**Total rating the problem as serious:** [TO FILL] of 5
