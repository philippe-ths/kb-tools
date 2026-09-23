# Laws of Software Engineering. A Landscape Tour.

## Overview of this guide.

Software engineering has accumulated a large body of informal laws, principles, and rules of thumb. They are not laws in the scientific sense. They are observations that keep proving useful across teams, projects, and decades.

This guide walks through the landscape in seven groups. Architecture. Teams. Planning. Quality. Scale. Design. Decisions. You will finish with a mental map of the most important ones and why they matter.

The goal is not memorisation. The goal is recognition. When you meet one of these patterns at work, you should be able to name it, which often makes the next decision easier.

Key term. A software engineering law is a repeatable pattern about how code, teams, or systems behave under pressure. Treat it as a warning light, not a physical constant.

---

## Topic one. Architecture laws.

Architecture laws describe how systems behave when you try to build, split, or scale them. They matter because most expensive mistakes in software are architectural, and they are hard to undo later.

Teaching technique used here. Analogy. Think of a building. You can repaint a wall cheaply, but moving the foundations is a different conversation. Architecture laws are about the foundations.

Conway's Law says that the shape of a system ends up mirroring the communication structure of the organisation that built it. If three teams build a compiler, you tend to get a three-pass compiler. If your backend and frontend teams do not talk, your Application Programming Interface (A.P.I.) will show the seams.

Gall's Law says that complex systems that work have almost always grown out of simpler systems that worked. Trying to design a complex system from scratch tends to fail. Start small, get it working, then grow it.

Tesler's Law, also called the Conservation of Complexity, says every system has an irreducible amount of complexity. You can move that complexity around between the software, the hardware, and the user, but you cannot delete it.

The Law of Leaky Abstractions says that all non-trivial abstractions leak some of the messy reality they were supposed to hide. Your Object-Relational Mapper (O.R.M.) hides S.Q.L., until a performance problem forces you to read the generated queries.

The C.A.P. Theorem, which stands for Consistency, Availability, and Partition tolerance, says a distributed data store can promise only two of those three properties at any moment. When the network splits, you must choose between being consistent or being available.

Hyrum's Law says that with enough users of your A.P.I., every observable behaviour of your system will end up being relied on by someone. That includes bugs and accidents. This is why breaking changes are so painful.

The Fallacies of Distributed Computing is a list of eight false assumptions junior designers tend to make. The network is reliable. Latency is zero. Bandwidth is infinite. The network is secure. Topology does not change. There is one administrator. Transport cost is zero. The network is homogeneous. All eight are wrong, and systems fail when you forget.

Source caveat. The list is usually attributed to Peter Deutsch and James Gosling at Sun Microsystems, with the eighth fallacy added later. The wording varies slightly across sources, so if you are quoting it formally, check the original.

Common mistake. Assuming the Second-System Effect will not hit you. After a small project succeeds, teams often try to rewrite it as a grand unified platform. The rewrite usually collapses under its own weight.

Zawinski's Law is a wry observation that every program expands until it can read email. It is a joke, but the point is real. Scope creep is the default state.

Learning takeaway. Architecture laws push you toward small, evolvable systems with honest abstractions, and warn you that distributed systems punish naive thinking.

---

## Topic two. Team laws.

Team laws describe what happens to productivity, knowledge, and decision-making when humans work together. They matter because software is built by groups, and group dynamics set the ceiling on what the code can become.

Teaching technique used here. Contrast. We will contrast what managers hope for with what these laws predict actually happens.

Brooks's Law says that adding people to a late project makes it later. New people need training, and that training comes from the people who were already busy. Communication overhead grows faster than the headcount.

The Ringelmann Effect says individual productivity drops as groups grow. Ten people in a room do not deliver ten times the work of one person. Coordination cost eats the gains.

Dunbar's Number suggests a human can maintain roughly one hundred and fifty stable relationships. Above that, you need formal structure. This is why large engineering orgs end up with tribes, guilds, and reporting lines.

Source caveat. The figure of one hundred and fifty is the commonly cited number, but Dunbar's original work gives a range from about one hundred to two hundred and thirty. Recent studies have also challenged whether a single cognitive limit exists at all. Treat it as a rule of thumb, not a constant.

Price's Law says the square root of the group does half the work. In a team of one hundred, around ten people produce fifty percent of the output. This is uncomfortable but consistent across creative fields.

Source caveat. Price's original work was about scientific publication output in the nineteen sixties, not general team productivity. Its extension to software teams is a popular modern reading, not something Price himself measured.

The Bus Factor is the number of people on your team who would need to be hit by a bus before the project stalls. A bus factor of one is a crisis waiting to happen. Good teams document, rotate, and pair to raise it.

The Peter Principle says that in a hierarchy, people are promoted to their level of incompetence. A great engineer gets promoted to manager and may be bad at it, and stays there because promotions stop.

The Dilbert Principle is a sharper cousin of the Peter Principle. Some companies deliberately promote weak performers into management, on the theory that they can do less damage there. Treat it as satire that sometimes rings true.

Source caveat. The Dilbert Principle started as a joke by cartoonist Scott Adams, not as a studied phenomenon. It is included in most lists of software engineering laws for cultural reasons, but it has no empirical basis. Use it as a warning about incentive design, not as a theory.

Putt's Law says that those who understand technology do not manage it, and those who manage it do not understand it. It is a warning to both sides. Engineers should learn to communicate with leadership, and leaders should stay close to the work.

Tutor note. Conway's Law belongs to both Architecture and Teams. If you want to change your architecture, you often have to change your team structure first. This is called the Inverse Conway Manoeuvre.

Learning takeaway. Teams are not linear multipliers of individual output. Communication cost, skew in contribution, and key-person risk dominate what a team can ship.

---

### Tutor-style question and answer.

Question. You are three months late on a project. Leadership offers to add five new engineers. What should you expect, and what two laws are in play?

Answer. Expect the project to get later before it gets faster. Brooks's Law predicts the short-term slowdown from onboarding overhead. The Ringelmann Effect predicts that the larger group will also lose per-person output to coordination cost. The better move is usually to cut scope, not add people.

---

## Topic three. Planning laws.

Planning laws describe how estimates, deadlines, and measurements behave in the real world. They matter because most software projects miss their dates, and understanding why is the first step to doing it less badly.

Teaching technique used here. Why it matters. Every one of these laws maps to a specific pain you have probably felt.

Parkinson's Law says work expands to fill the time available. Give a team three months for a two-week task, and it will take three months. This is why short iterations often produce more than long ones.

Hofstadter's Law says it always takes longer than you expect, even when you take Hofstadter's Law into account. The recursion is the joke, but the advice is to add a buffer and then add another.

The Ninety-Ninety Rule says the first ninety percent of the code takes ninety percent of the time, and the last ten percent takes the other ninety percent. The tail is always longer than it looks. Integration, edge cases, and polish swallow weeks.

Knuth's Optimization Principle says premature optimization is the root of all evil. The full quote adds that we should forget about small efficiencies in about ninety-seven percent of cases, but pay attention to the critical three percent. First make it work, then make it right, then make it fast, and only where it matters.

Source caveat. The ninety-seven percent figure comes from Knuth's nineteen seventy-four paper Structured Programming with Go To Statements. The quote is often trimmed to just "premature optimization is the root of all evil", which loses the important nuance that the other three percent really does matter.

Goodhart's Law says that when a measure becomes a target, it stops being a good measure. Count bugs closed, and people will close bugs. Count lines of code, and people will write verbose code. The metric is gamed, and you lose the signal you wanted.

Gilb's Law is a useful counterweight. It says anything you need to quantify can be measured in some way that beats not measuring at all. You will not measure perfectly, but you can still measure usefully, as long as you remember Goodhart.

Common mistake. Turning a noisy proxy metric into a target and tying bonuses to it. You get the number you asked for, and not the outcome you wanted.

Learning takeaway. Plans slip in predictable ways. Estimate with humility, keep iterations short, and be careful what you measure, because people respond to what is counted.

---

## Topic four. Quality laws.

Quality laws describe how code stays healthy or rots over time. They matter because most software is maintained far longer than it was planned to be, and decay compounds.

Teaching technique used here. Building from simple to complex. We start with a one-line rule and end with the evolution of whole systems.

The Boy Scout Rule says leave the code better than you found it. Tiny improvements on every visit stop the slow rot. It only works if everyone does it.

The Broken Windows Theory, borrowed from urban policing research, says that visible decay invites more decay. If one test is flaky and ignored, soon five are. Fix the first broken window quickly, or accept that the area is now the kind of place where windows get broken.

Murphy's Law, also known as Sod's Law, says anything that can go wrong will go wrong. In software, this translates to aggressive error handling, defensive programming, and not trusting input.

Postel's Law, from the early internet, says be conservative in what you send and liberal in what you accept. It is how imperfect systems interoperate. It is also controversial today, because being too liberal on input has allowed real bugs to spread.

Source caveat. Modern security and protocol designers increasingly argue Postel's Law was a mistake. The Internet Engineering Task Force has published drafts pushing back on it, pointing out that accepting malformed input has made some protocols impossible to evolve and has hidden security bugs. So this one is actively contested, not settled wisdom.

Linus's Law says that given enough eyeballs, all bugs are shallow. More reviewers and users mean faster detection. This is a large part of the case for open source and code review.

Kernighan's Law says debugging is twice as hard as writing the code in the first place. Therefore, if you write code as cleverly as possible, you are, by definition, not clever enough to debug it. Write simple code.

The Testing Pyramid says your test suite should be shaped like a pyramid. Many fast unit tests at the base. Fewer integration tests in the middle. A small number of end-to-end or user-interface tests at the top. This keeps feedback fast and cheap.

The Pesticide Paradox says the same tests, run repeatedly, catch fewer new bugs over time. You have to evolve the tests, just like pests evolve resistance to pesticide.

Technical Debt is the cost of shortcuts taken in code. Like financial debt, it is sometimes worth taking, but unpaid interest compounds. At some point, debt service eats most of your velocity.

Lehman's Laws of Software Evolution describe how long-lived software behaves. Useful systems must keep changing to stay useful. Their complexity grows unless work is done to reduce it. Their quality decays unless it is actively maintained. In short, software is a garden, not a statue.

Source caveat. There are actually eight named Lehman's Laws, formulated between nineteen seventy-four and nineteen ninety-six. I have given you the spirit of the three most quoted ones, Continuing Change, Increasing Complexity, and Declining Quality. If you want the full set, including Self-Regulation, Conservation of Organisational Stability, Conservation of Familiarity, Continuing Growth, and Feedback System, check Lehman's original papers.

Sturgeon's Law says ninety percent of everything is crap. Apply it to libraries, frameworks, and conference talks. Be selective.

Learning takeaway. Quality is not a state you reach, it is a rate you defend. Small habits, honest tests, and willingness to pay down debt keep a codebase from rotting.

---

### Tutor-style question and answer.

Question. Your team has added a dashboard that measures lines of code per engineer per week. After a month, output on the dashboard is up, but bug counts are also up and reviews are slower. What law explains this?

Answer. Goodhart's Law. The moment lines of code became the target, it stopped measuring productive work. Engineers, consciously or not, are writing more code to make the metric move, and quality is paying for it. The fix is to pick an outcome you actually care about, such as customer incidents or lead time, and resist turning any proxy metric into a scoreboard.

---

## Topic five. Scale laws.

Scale laws describe what happens when you add more resources, more data, or more users. They matter because scaling failures are expensive and often surprise teams that did not do the arithmetic.

Teaching technique used here. Practical use-case. Each law comes with a situation where it bites.

Amdahl's Law says the speedup from parallelising a workload is limited by the part that cannot be parallelised. If ten percent of your job is sequential, the maximum possible speedup is ten times, no matter how many cores you throw at it. This is why naive parallelisation plateaus.

Gustafson's Law is the optimistic counterpart. It says that as problems get bigger, the sequential fraction often shrinks, and parallel hardware becomes more useful. Amdahl assumes a fixed problem size. Gustafson assumes the problem scales up.

Metcalfe's Law says the value of a network grows roughly with the square of the number of users. Two phones connect one pair. Ten phones connect forty-five pairs. This is why network effects create winner-take-most markets.

Tutor note. Scale laws are where intuition breaks first. A mental model that works at ten users often fails silently at ten million. Always ask, what does this look like at one hundred times the load.

Learning takeaway. Scale is not just more of the same. Serial bottlenecks cap parallel gains, bigger problems behave better under parallelism than smaller ones, and networks grow in value non-linearly.

---

## Topic six. Design principles.

Design principles are rules of thumb for structuring code day to day. They matter because they shape how easy or painful the next change will be.

Teaching technique used here. Memory aid. Most of these have short, catchy names for a reason. Use the names.

Y.A.G.N.I., which stands for You Aren't Gonna Need It, says do not build features until you actually need them. Speculative features add cost now and usually get deleted later.

D.R.Y., which stands for Don't Repeat Yourself, says each piece of knowledge in a system should have one authoritative representation. Duplicated logic drifts out of sync and creates bugs.

K.I.S.S., which stands for Keep It Simple, Stupid, says designs should be as simple as possible but no simpler. Complexity is the main enemy of reliability.

The S.O.L.I.D. principles are five object-oriented design guidelines. Single responsibility. Open for extension, closed for modification. Liskov substitution, meaning subtypes should be usable as their parent type. Interface segregation, meaning many small interfaces beat one large one. Dependency inversion, meaning depend on abstractions not concretions. Together they push you toward modular, testable code.

The Law of Demeter says a unit of code should only talk to its immediate friends, not reach through one object to poke at another. It is sometimes called the principle of least knowledge. Chains like a.getB().getC().doThing() are a warning sign.

The Principle of Least Astonishment says software should behave the way a reasonable user expects. If your delete button restores files, you have violated it. Surprise is a cost.

Common mistake. Treating D.R.Y. as an absolute. Two pieces of code that look the same today may represent different concepts that will evolve apart. Premature deduplication can create brittle coupling. The rule of three, wait until you see the pattern three times before extracting it, is a healthier default.

Learning takeaway. Design principles pull in different directions on purpose. The skill is knowing which one applies in the current situation, not applying all of them at once.

---

### Tutor-style question and answer.

Question. A colleague proposes parallelising a batch job across thirty-two cores. They expect a thirty-two-times speedup. You look at the code and see a single database write step that cannot be parallelised and takes about twenty percent of the total runtime. What is the realistic ceiling?

Answer. Amdahl's Law gives you the answer. If twenty percent is sequential, the maximum speedup is one divided by zero point two, which is five times, even with infinite cores. Thirty-two cores will not get you anywhere near thirty-two times. The useful next move is to attack the sequential portion, for example by batching writes, before adding more parallelism.

---

## Topic seven. Decision-making laws.

Decision-making laws come from psychology, philosophy, and investing, but they apply constantly in engineering work. They matter because most bad technical decisions are bad reasoning dressed in technical clothes.

Teaching technique used here. Common mistake plus why it matters. Each of these names a specific trap.

The Dunning-Kruger Effect describes how people with little knowledge of a topic often overestimate their ability. Experts, by contrast, tend to be more cautious. The cure is not confidence, it is exposure to people who know more.

Source caveat. The original nineteen ninety-nine study has been challenged in recent years. Several statisticians have argued the classic Dunning-Kruger graph is partly a mathematical artefact of how the data was plotted, not a pure psychological effect. The phenomenon of overconfident beginners is still real in everyday experience, but the strong version of the effect is less settled than pop science suggests.

Hanlon's Razor says never attribute to malice what is adequately explained by carelessness or stupidity. That outage was probably not sabotage. It was probably a tired engineer and a bad config.

Occam's Razor says the simplest explanation that fits the facts is usually the right one. Before you blame a subtle race condition, check whether someone just deployed the wrong build.

The Sunk Cost Fallacy is the urge to keep investing in something because you already invested in it. Two years of work on a failing project is not a reason to keep going. It is information about the cost of stopping, nothing more.

The Map Is Not the Territory is a reminder that your diagram, your model, your metric, is not the real system. Your service map shows intended behaviour. Production shows actual behaviour. Stay humble.

Confirmation Bias is the tendency to notice information that supports your existing view and ignore information that contradicts it. In debugging, it shows up as fixating on one theory and missing the actual cause. Good engineers actively look for disconfirming evidence.

Amara's Law, often paired with the Hype Cycle, says we overestimate the impact of a technology in the short run and underestimate it in the long run. Useful as a corrective to both hype and cynicism.

The Lindy Effect says the longer a technology has been around, the longer it is likely to last. S.Q.L. has been with us for fifty years, and will probably outlive most of the current frameworks. Prefer proven tools for load-bearing parts of your stack.

First Principles Thinking is breaking a problem down to the most basic truths you actually know, and reasoning up from there. It is the opposite of reasoning by analogy. Useful when the usual answers are clearly failing.

Inversion is solving a problem by asking how you could guarantee the opposite outcome, and then avoiding those actions. Instead of asking how to make the system reliable, ask what would make it unreliable, and stop doing those things.

The Pareto Principle, also called the eighty twenty rule, says roughly eighty percent of the effects come from twenty percent of the causes. Twenty percent of the code causes eighty percent of the bugs. Twenty percent of customers generate eighty percent of the support load. Find that twenty percent.

Cunningham's Law says the fastest way to get the correct answer online is not to ask a question, but to post the wrong answer. People will rush to correct you. Use this one ethically.

Learning takeaway. Most decision errors are not technical, they are cognitive. Naming the bias as it happens is half the fight.

---

## Conclusion.

The laws of software engineering are a shared vocabulary for things that keep happening. Architecture laws warn you about irreducible complexity and the cost of distributed systems. Team laws tell you that headcount is not a dial. Planning laws say estimates are hard and metrics are traps. Quality laws describe slow decay and how to fight it. Scale laws remind you that intuition breaks at size. Design principles give you short names for good instincts. Decision laws name the biases that bend good engineers toward bad choices.

None of these are physical laws. All of them have exceptions. Their value is as a diagnostic vocabulary. When you catch yourself, or your team, doing one of these things, naming it often unlocks the fix.

The landscape is wider than any one engineer will ever fully use. Start by noticing which ones show up in your current work, and let the rest wait until they are needed.

---

## Practical next steps.

Pick three laws from this guide that match a current problem on your team. Write them on a sticky note and watch for them for a week. Notice when they fire.

Run a short retrospective using Inversion. Ask, what would we have to do to guarantee this project fails? Then check how many of those things are already happening.

Measure your team's Bus Factor honestly. For each critical system, list who could own it if the current owner vanished. If any answer is nobody, that is your next piece of documentation or pairing work.

Audit one metric your team is tracking against Goodhart's Law. Ask whether the metric is still measuring the outcome you care about, or whether people are optimising the number at the expense of the goal.

Read the one-line description of all fifty-six laws on the source site, and bookmark the three that surprised you most. Surprise is a good signal of where your current mental model is weakest.

---

## Key sources used.

The lesson is structured around the collection at https://lawsofsoftwareengineering.com/ by Dr. Milan Milanović, which organises fifty-six named laws across seven categories. The names, categories, and one-line summaries follow that source.

The extended explanations, examples, and teaching framing are original to this guide and were not cross-referenced against external sources at the time of writing. Specific numeric claims, attributions, and the laws flagged with Source caveat notes above are the areas most worth verifying independently before using them in a talk, article, or anything formal.
