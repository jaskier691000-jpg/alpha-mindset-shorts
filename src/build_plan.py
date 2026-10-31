"""Build topic_plan.json: 730 monologue topics (2 a day for one year), mixed across categories.

The first 60 (month 1) are fixed below; the rest are spread evenly so the same category rarely comes
twice in a row. Dated topics (SEASONAL) are moved to their day. Titles are themes for the weekly writer,
not captions. Set START to the real launch day before going live, then run: python src/build_plan.py
"""
import re
import sys
from datetime import date, timedelta

from common import ROOT, save_json

START = date(2026, 11, 1)  # launch day (the job posts topics in order)
SLOTS = ["08:00", "20:00"]

CATEGORIES = {
    "Discipline": """Nobody is coming to save you, Discipline beats motivation, Do it tired, Do it when nobody is watching,
        The boring work wins, Keep your promises to yourself, Show up every single day, Small wins every day,
        Consistency is a superpower, Discipline is self respect, The hard thing first, No zero days,
        Do it even when you hate it, Motivation is a liar, Feelings are not instructions, Earn your rest,
        Never miss twice, Win the first hour, Discipline is freedom, Delayed gratification, Do the reps, One more rep,
        Raise your standards, The minimum you will accept, Stop negotiating with yourself, The two minute start,
        Habits build the man, Break the streak of excuses, Discipline when it rains, The obsessed have no weekends,
        The price of discipline, The price of regret, Commit before you feel ready, Hard choices easy life,
        Easy choices hard life, Your calendar never lies, Discipline in the small things, Clean room clear mind,
        Eat like you respect yourself, Train your willpower, Willpower is a muscle, Remove the temptation,
        Design your environment, Discipline over talent, Talent is not enough, The grind nobody claps for,
        Results take time, The compound effect, Ninety days of silence, Stop starting over, Finish what you start,
        Do not break the chain, Systems beat goals, Discipline in your speech, Discipline with money,
        Discipline with your phone, Discipline at night, The last hour of your day, The discipline of rest,
        Discipline when you are winning, Discipline when you are losing, Stay hungry, Comfort is the enemy,
        Choose your hard, The cost of easy, Self control is strength, Master your impulses,
        The voice that says quit, Keep going when it is boring, Discipline is a decision, Every day is a vote,
        Become unstoppable, Do what you said, Trust is built in private, Integrity when no one sees,
        Discipline is love for your future self, The quiet discipline of champions, Repetition is the secret,
        Discipline on bad days""",
    "Mornings and routine": """Win the morning win the day, Wake up before the world, The five am club, Your alarm is a test,
        The snooze button lies, Cold water first, The first ten minutes, No phone in the morning,
        Morning walk morning mind, Plan the day the night before, The power of a written plan, Journal like a warrior,
        Make your bed like a soldier, Sunlight before screens, Silence before noise, Read before you scroll,
        Move before you think, The evening routine, Shut down the day properly, Sleep is a weapon, Bedtime discipline,
        The Sunday reset, Monday is a gift, The weekly review, Routines beat moods, The power of rituals,
        Same time every day, Lay out your clothes, Pack your gym bag tonight, Water before coffee,
        Stretch your body wake your mind, Breathe before battle, See your day before it starts, Say your goals out loud,
        Gratitude for warriors, One page a day, The night owl excuse, Early is a mindset, Protect your mornings,
        Your first decision of the day, The quiet hours, Before sunrise, Routine builds confidence,
        The boring morning wins, Morning workouts, Your routine is your identity, Fix your sleep fix your life,
        Lights out on time, The power of a checklist, Morning words that build you, How winners start the day,
        A morning without excuses, The commute is your classroom, Lunch break discipline, The last coffee rule""",
    "Body and training": """The gym is a mirror, Lift heavy things, Your body keeps the score, Sweat is weakness leaving,
        Train when you do not want to, Leg day character, The last set matters, Progressive overload in life,
        Run when you want to stop, Cardio for the mind, The fat you keep is the excuse you keep, Abs are made in silence,
        Strength is a skill, Train like a warrior, Fight training, Boxing teaches humility,
        Get hit and stay standing, Pain is information, Soreness is a receipt, Rest days are part of the work,
        Your body is your first home, Eat for strength, Sugar is a thief, Alcohol steals your edge,
        Posture of a leader, Walk like you mean it, Stand tall, Hydration is discipline, Ten thousand steps,
        Push ups every morning, Pull ups and pride, The squat and the soul, Deadlift your doubts, Train in the rain,
        The empty gym, Gym at night, Gym at dawn, Comparison in the gym, Your only competition, Ego lifting,
        Form before weight, Consistency over intensity, One hour a day, Old man strength, Strong body strong mind,
        Fitness is self respect, Look like you train, Recovery is a weapon, Cold showers, Ice baths and willpower,
        Breath control, Walking as therapy, Hike a mountain, Climb the stairs, Run your first mile,
        Train with someone better, Train alone, Your body hears your thoughts, Strength for your family,
        Never skip the warm up""",
    "Focus and distraction": """Your phone is a slot machine, Kill the notifications, Deep work, One thing at a time,
        Attention is your currency, Dopamine detox, Stop scrolling start building, The algorithm owns you,
        Delete the apps, Boredom is a gift, Silence is focus, Protect your attention, Multitasking is a lie,
        Single tasking, The first hour of work, Turn off the noise, Focus like a sniper, Tunnel vision,
        Ignore the crowd, The power of saying no, Busy is not productive, Distraction is the enemy,
        Screen time is life time, Your feed shapes your mind, Unfollow the noise, Read more watch less,
        Learn in silence, Focus on the process, Eyes on your own lane, Stop checking stop chasing,
        Do the work not the talk, Clarity before action, Write your priorities, Make one decision, Too many goals,
        Focus is a muscle, Hours of focus, Your desk is your battlefield, Turn work into a ritual, The flow state,
        Distraction is a choice, Put the phone in another room, The cost of a notification, News is noise,
        Opinions are distractions, Stay off the sidelines, Concentrate your energy, The narrow path,
        Finish one thing, Focus when it is hard, Train your attention, Quiet mind loud results,
        Your attention is sacred, Remove the clutter, Focus on what you control""",
    "The path alone": """Walk alone if you must, The lonely season, Lone wolf season, Isolation builds kings,
        Nobody understands your vision, Your circle will shrink, Outgrow people, Silence your plans, Move in silence,
        Let results talk, Not everyone is coming with you, Alone but not lonely, Enjoy your own company,
        The quiet years, Friends who pull you down, Choose your circle, The five people around you,
        Leave the group chat, Stop seeking approval, You do not need applause, Be misunderstood,
        The price of being different, The crowd goes the wrong way, Lead from the front, Walk your own path,
        Your path is not for everyone, Solitude is strength, Time alone with your thoughts, Disappear and improve,
        The comeback season in silence, Dark days alone, Nobody sees the process, Unseen work,
        Isolation is not punishment, Build in the dark, The night shift of success, Doubted by everyone,
        Be your own coach, Trust yourself, Stand alone, One man army, The road less taken, Alone at the top,
        The loneliness of ambition, Saying goodbye to the old you, Leave the comfort of the pack,
        The wolf who walks alone, Silent warrior, Quiet confidence, Peace in solitude""",
    "Failure and comeback": """Fall seven times rise eight, Failure is a teacher, Your rock bottom is a foundation,
        The comeback is stronger, Lose with honor, Rejection is redirection, Fired and reborn, Broke but building,
        Starting from zero, Start again, Second chances, Bad days build good men, The day you wanted to quit,
        Getting knocked down, Get back up, Mistakes are tuition, Own your failures, Stop blaming others,
        Responsibility is power, Regret or results, The pain of losing, Learn from losses, Heartbreak and the gym,
        After the breakup, When life hits hard, Hard times create strong men, The storm will pass,
        Through the fire, Pressure makes diamonds, Scars are proof, Wounds into wisdom, Turn pain into power,
        The setback is a setup, Never give up, Give up and stay average, One more try, Failure is not final,
        Embarrassed and still going, Laughed at and still building, They doubted you, Prove them wrong,
        Prove yourself right, Comeback mentality, Rise from the ashes, The phoenix, Rebuild yourself,
        The new version of you, Losing is a lesson, The last place lesson, From broke to built,
        Dark days and discipline, When motivation dies, When nobody believes, Keep fighting, The fight is not over,
        Endure, Resilience, Grit, Hold the line, Stay in the fight""",
    "Fear and courage": """Fear is a liar, Do it scared, Courage is not the absence of fear, Face your fears,
        The fear of judgment, What would you do without fear, The comfort zone is a cage, Step into the unknown,
        Take the risk, The cost of playing safe, Speak up, Ask the question, Make the call, Courage in small moments,
        Fear of failure, Fear of success, The imposter feeling, Overthinking kills, Act before you are ready, Jump,
        Leap of faith, The brave choice, Stand up for yourself, Say no without guilt, Walk into the room,
        Confidence is built, Fake it or build it, Fear of rejection, Approach with confidence, Speak in public,
        Bet on yourself, Courage is a habit, Be the first, Lead when scared, Fear of being alone,
        Uncomfortable conversations, Courage at work, Scared to launch, Quit the wrong job, Move to a new city,
        Fear and the warrior, The Spartan mindset, Samurai courage, Die with no regrets, Live before you die,
        Danger and growth, Nerves are energy, Pressure is a privilege, Embrace the cold, Comfort is a slow death,
        Courage over comfort, Write down your fears, Brave enough to be bad, Courage to change, Fear will not wait""",
    "Time and urgency": """Time is the only currency, You are running out of time, The clock is ticking,
        Someday is not a day, One year from now, Ten years from now, Your eighty year old self, Life is short,
        Stop wasting days, Four thousand weeks, Every hour counts, Tomorrow is not promised, Do it now,
        Procrastination is a thief, Waiting for the right moment, The best time was yesterday, Now is the moment,
        Seasons of life, Your twenties, Your thirties, It is never too late, Too old to start,
        Time with your parents, Time with your kids, How you spend your evenings, The last day of your life,
        Memento mori, Urgency without panic, Patience and urgency, Short term pain long term gain,
        Plant trees today, The time will pass anyway, A wasted Sunday, Sleep or scroll, Your days become your life,
        Give yourself a deadline, Hour by hour, The math of a day, The hourglass,
        Spend time like money, Life is a countdown, The present moment, Make the days count, No more next week,
        The last day of the year, A new year starts now""",
    "Ambition work and money": """Work in silence, Outwork everyone, Hard work beats talent, Build your empire,
        Become rich in skills, Money is a tool, Stop buying things to impress, Save first spend later,
        Invest in yourself, The best investment, Learn a high value skill, Learn to sell, Your nine to five,
        Side hustle nights, Build while they sleep, The grind is lonely, Hustle with purpose, Ambition is not greed,
        Dream big work bigger, Goals on paper, Plans without action, Execution is everything,
        Done is better than perfect, Start the business, Own something, Be an owner not a worker, The boss mindset,
        Negotiate your worth, Ask for more, Respect your time, Overnight success takes years, The long game,
        Patience in business, Lessons from the poor years, Rich habits, Poor habits, Debt is a chain,
        Live below your means, Luxury can wait, Earn it before you show it, Quiet money, Flex nothing,
        Work ethic is respect, Become valuable, Skills pay the bills, Learn every day, Read like a CEO,
        Mentors and books, Network up, Ambition at twenty, Ambition at forty, Be obsessed, Healthy obsession,
        Burnout and balance, Work smart and hard, Bet on the long term, Build a legacy business,
        From nothing to something, Hungry for more, The extra hour""",
    "Mindset": """Your mind is a battlefield, Talk to yourself like a champion, Silence the inner critic,
        You become what you repeat, Identity before results, Act like the man you want to be, Believe before you see,
        Confidence comes from evidence, Self belief, The mindset of a lion, Think like a king, The wolf you feed,
        Victim or victor, Control the controllables, Stop complaining, Gratitude is strength, Abundance mindset,
        Scarcity thinking, Growth mindset, Fixed mindset traps, Your limits are lies, The impossible is temporary,
        Expect hardship, Embrace the suck, Mental toughness, Train your mind daily, Visualize winning,
        Speak your future, Rewrite your story, Your past is not your prison, Leave the victim story,
        From overthinking to action, Decide who you are, Raise your self image, Self respect, Self worth,
        Speak less mean more, Think in decades, Calm under pressure, Mind over mood, Excuses are stories,
        Stop waiting to feel ready, Hunger over comfort, The mental reps, Mindset is a muscle, Positive is not soft,
        Realistic optimism, Accept and attack, Pressure reveals you, Who you are at your worst,
        The man in the mirror, Love the challenge, Your thoughts become things, Choose your hard thoughts,
        The stories you tell, Win the war inside, Do not believe every thought, Think like a soldier, Mental armor""",
    "Emotional control and stoicism": """Control your emotions, Do not react, Respond do not react, Silence is power,
        Anger is a weak leader, Calm is a superpower, Stoic strength, The Marcus Aurelius mindset, Seneca on time,
        Epictetus and control, Amor fati, The obstacle is the way, Pain is certain suffering is optional,
        Detach from outcomes, Let it go, Forgive and move, Revenge is wasted energy, Do not take it personally,
        Insults are noise, Ego is the enemy, Humility is strength, Patience is power, Stay calm in chaos,
        The storm inside, Master your mood, Jealousy is a waste, Envy and comparison, Peace over drama,
        Walk away from drama, Silence wins arguments, Lose the need to be right, Accept what you cannot change,
        Change what you can, Emotions are waves, Cry and keep going, Men and feelings, Strong men talk,
        Ask for help, Getting help is strength, Sadness and strength, Heartbreak lessons, Loneliness at night,
        Anxiety and action, Breathe through panic, Fear and calm, Stoic mornings, Stoic evenings, Write out your anger,
        Be like water, The rock in the river, Unshakeable, Inner peace, Quiet strength, Emotional discipline,
        Enough is enough""",
    "Purpose legacy and family": """Find your why, Live with purpose, Your legacy starts today, Be the example,
        Your kids are watching, Be the father you needed, Make your parents proud, Protect your family,
        Provide and protect, Lead your home, Break the cycle, Generational change,
        What will they say at your funeral, Build something that lasts, Serve something bigger,
        Purpose over pleasure, Meaning over money, Live for something, Who are you doing it for,
        The people who believed in you, Honor your mother, Honor your father, Brotherhood, Loyalty, Be a good man,
        Strong and kind, Gentle strength, Respect is earned and given, A man of his word, Character is destiny,
        Integrity, Be a role model, Mentor someone, Give back, Gratitude for what you have, Faith and fight,
        Your mission, The calling, Legacy over likes, Lead by example, The last chapter, Plant seeds,
        Teach your son, Be the rock, A life well lived, A letter to fathers""",
    "Respect and standards": """Set boundaries, Your standards are your life, Stop being available, Value your time,
        Walk away, Know your worth, Self respect first, Do not chase, Attract do not chase, Respect is earned,
        Earn respect quietly, People treat you how you allow, Say no more often, Cut toxic people,
        Stop explaining yourself, Do not beg for attention, Stop people pleasing, The nice guy trap,
        Kindness is not weakness, Firm and fair, Keep your word, Do not gossip, Speak with intention, Eye contact,
        Presence and a firm handshake, Dress with respect, Grooming is discipline, Presence over noise,
        Calm confidence, The power of the pause, Do not overshare, Privacy is power, Be hard to manipulate,
        Spot the users, Loyalty tests, Fake friends, Real ones, Your reputation, Principles over popularity,
        Non negotiables, Raise the bar, No tolerance for nonsense, Protect your peace, Your energy is limited,
        Who gets your time, Leave the table, Know when to leave, Standards in love, High value habits,
        Self respect is attractive""",
}

MONTH_1 = """Nobody is coming to save you, Discipline beats motivation, Do it tired, Your phone is a slot machine,
    Walk alone if you must, Fall seven times rise eight, Fear is a liar, Time is the only currency, Work in silence,
    Your mind is a battlefield, Control your emotions, Be the father you needed, Set boundaries,
    Win the morning win the day, The gym is a mirror, Motivation is a liar, Kill the notifications,
    Your circle will shrink, Your rock bottom is a foundation, Do it scared, Someday is not a day, Outwork everyone,
    Talk to yourself like a champion, Silence is power, Find your why, Know your worth, Wake up before the world,
    Train when you do not want to, Keep your promises to yourself, Dopamine detox, Move in silence, Get back up,
    The comfort zone is a cage, You are running out of time, Money is a tool, The wolf you feed,
    The obstacle is the way, Your kids are watching, Stop being available, The snooze button lies, Lift heavy things,
    Do it when nobody is watching, Deep work, Nobody understands your vision, Hard times create strong men,
    Take the risk, One year from now, Build while they sleep, Victim or victor, Calm is a superpower,
    Make your parents proud, Walk away, Sleep is a weapon, Run when you want to stop, The boring work wins,
    Attention is your currency, Isolation builds kings, Scars are proof, Bet on yourself, Memento mori"""

# dated topics: slug -> day (moved to the morning slot of that day)
SEASONAL = {
    "the-last-day-of-the-year": "2026-12-31",
    "a-new-year-starts-now": "2027-01-01",
    "a-letter-to-fathers": "2027-06-20",  # Father's Day (US, UK, Canada)
}


def split(text):
    return [t.strip() for t in text.replace("\n", " ").split(",") if t.strip()]


def slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower().replace("'", "")).strip("-")


def main():
    category_of, problems = {}, []
    for category, text in CATEGORIES.items():
        for title in split(text):
            if slug(title) in category_of:
                problems.append(f"duplicate: {title}")
            category_of[slug(title)] = (category, title)
    counts = {c: len(split(t)) for c, t in CATEGORIES.items()}
    if len(category_of) != 730:
        problems.append(f"{len(category_of)} topics in total, expected 730 ({counts})")

    month_1 = [slug(t) for t in split(MONTH_1)]
    problems += [f"month 1 topic not in a category: {s}" for s in month_1 if s not in category_of]
    problems += [f"month 1 topic has a date: {s}" for s in month_1 if s in SEASONAL]
    problems += [f"dated topic not in a category: {s}" for s in SEASONAL if s not in category_of]
    if len(set(month_1)) != 60:
        problems.append(f"month 1 has {len(set(month_1))} different topics, expected 60")
    if problems:
        sys.exit("\n".join(problems))

    # spread the rest evenly: item k of a category with n items sits at position (k + 0.5) / n
    rest = []
    for category, text in CATEGORIES.items():
        items = [slug(t) for t in split(text) if slug(t) not in month_1 and slug(t) not in SEASONAL]
        rest += [((k + 0.5) / len(items), category, s) for k, s in enumerate(items)]
    order = month_1 + [s for _, _, s in sorted(rest)]

    # then each dated topic goes in the morning slot of its date (evening if the morning is taken)
    wanted = {}
    for s, day in SEASONAL.items():
        i = (date.fromisoformat(day) - START).days * 2
        while i in wanted:
            i += 1
        wanted[i] = s
    for i in sorted(wanted):
        order.insert(i, wanted[i])

    plan = []
    for i, s in enumerate(order):
        category, title = category_of[s]
        plan.append({"n": i + 1, "date": str(START + timedelta(days=i // 2)), "time": SLOTS[i % 2],
                     "id": s, "category": category, "title": title})
    save_json(ROOT / "topic_plan.json", plan)
    print(f"{len(plan)} topics, {plan[0]['date']} -> {plan[-1]['date']}")
    print("per category: " + ", ".join(f"{c} {n}" for c, n in counts.items()))


if __name__ == "__main__":
    main()
