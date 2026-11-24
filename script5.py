import streamlit as st
import sqlite3
import requests
import json
import html
import os

# 1. Настройка вкладки браузера
st.set_page_config(page_title="English Media App", layout="wide")

# 2. Подключение к базе данных
conn = sqlite3.connect("smart_dict.db", check_same_thread=False)
cursor = conn.cursor()

# 3. Таблица слов
cursor.execute("""
    CREATE TABLE IF NOT EXISTS words (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        english_word TEXT NOT NULL,
        russian_translation TEXT NOT NULL,
        example_eng TEXT,
        example_rus TEXT
    )
""")
conn.commit()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS progress (
        section TEXT PRIMARY KEY,
        completed_at TEXT
    )
""")
conn.commit()


def translate_free(text, src="en", tgt="ru"):
    r = requests.get(
        "https://api.mymemory.translated.net/get",
        params={"q": text, "langpair": f"{src}|{tgt}"},
        timeout=10,
    )
    return r.json()["responseData"]["translatedText"]


def example_free(word):
    try:
        r = requests.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=10)
        data = r.json()
    except Exception:
        return ""
    if not isinstance(data, list):
        return ""
    for entry in data:
        for meaning in entry.get("meanings", []):
            for d in meaning.get("definitions", []):
                if d.get("example"):
                    return d["example"]
    return ""


def get_deepseek_key():
    try:
        key = st.secrets["DEEPSEEK_API_KEY"]
        if key:
            return key
    except Exception:
        pass
    return os.getenv("DEEPSEEK_API_KEY", "")


def get_card_deepseek(word):
    key = get_deepseek_key()
    if not key:
        raise RuntimeError("не найден ключ DEEPSEEK_API_KEY")

    prompt = (
        f"Ты преподаватель английского. Слово: '{word}'.\n"
        "Верни JSON с тремя полями:\n"
        "translation: перевод на русский (1-3 самых частых значения через запятую);\n"
        "example_eng: простое предложение уровня A2-B1 с этим словом;\n"
        "example_rus: перевод этого предложения на русский.\n"
        "Только JSON, без пояснений."
    )
    r = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": "deepseek-flash",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "max_tokens": 400,
        },
        timeout=30,
    )
    r.raise_for_status()
    data = json.loads(r.json()["choices"][0]["message"]["content"])
    return (str(data["translation"]).strip(),
            str(data["example_eng"]).strip(),
            str(data["example_rus"]).strip())


def get_card(word):
    try:
        return (*get_card_deepseek(word), "DeepSeek")
    except Exception as e:
        reason = str(e)
        translation = translate_free(word)
        ex_eng = example_free(word)
        if ex_eng:
            try:
                ex_rus = translate_free(ex_eng)
            except Exception:
                ex_rus = "Нет перевода примера"
        else:
            ex_eng = "No example found"
            ex_rus = "Пример не найден"
        return translation, ex_eng, ex_rus, f"запасной вариант (DeepSeek не ответил: {reason})"


st.markdown("""
    <style>
    div[data-testid="stMarkdownContainer"] p {
        font-size: 22px !important;
    }
    .st-af {
        font-size: 22px !important;
    }
    </style>
    """, unsafe_allow_html=True)


PLACEHOLDER = "Please choose an opinion..."


def show_video(path):
    if os.path.exists(path):
        st.video(path)
    else:
        st.warning(f"Видео «{path}» не найдено. Положите файл рядом с app.py.")
    st.caption("📖 Не знаешь какое-то слово? Добавь его в раздел «Мой словарь» в меню слева и узнай перевод!")


def is_done(prefix):
    """True, если раздел уже пройден."""
    cursor.execute("SELECT 1 FROM progress WHERE section = ?", (prefix,))
    return cursor.fetchone() is not None


def mark_done(prefix):
    """Запоминает, что раздел пройден."""
    cursor.execute(
        "INSERT OR IGNORE INTO progress (section, completed_at) VALUES (?, datetime('now'))",
        (prefix,)
    )
    conn.commit()


def menu_label(text, prefix):
    """Название кнопки меню, к пройденному разделу добавляется галочка."""
    return text + (" ✅" if is_done(prefix) else "")


def run_quiz(prefix, tasks, done_text):
    """
    Рисует раздел с заданиями.
    prefix    - короткое имя раздела (city, fruit, food, idiom): из него строятся ключи
    tasks     - список заданий
    done_text - поздравление в конце раздела
    """
    state_key = f"{prefix}_task"
    if state_key not in st.session_state:
        st.session_state[state_key] = 1

    total = len(tasks)
    n = st.session_state[state_key]
    if n > total:
        n = st.session_state[state_key] = total
    task = tasks[n - 1]

    side_left, center_col, side_right = st.columns([1, 4, 1])
    with center_col:
        if is_done(prefix):
            st.success("✅ Вы уже прошли этот раздел! Можете повторить задания ещё раз.")
            if st.button("🔄 Пройти заново с 1-го задания", key=f"reset_{prefix}", use_container_width=True):
                st.session_state[state_key] = 1
                for i in range(1, total + 1):
                    st.session_state.pop(f"{prefix}_ans_{i}", None)
                st.rerun()

        st.progress(n / total, text=f"Задание {n} из {total}")

        st.markdown(f"<h2 style='font-size: 28px;'>Задание {n}: Посмотрите видео и выполните задание</h2>",
                    unsafe_allow_html=True)
        st.markdown(
            f"<p style='font-size: 20px; font-weight: bold;'>Выполните задание: '{task['question']}'</p>",
            unsafe_allow_html=True)

        labels = [f"{i + 1}) {opt}" for i, opt in enumerate(task["options"])]
        answer = st.radio(
            "Варианты:",
            [PLACEHOLDER] + labels,
            index=0,
            key=f"{prefix}_ans_{n}",
            label_visibility="collapsed"
        )
        show_video(task["video"])

        if answer == labels[task["correct"]]:
            st.success("🎉 Absolutely correct! Great job.")
            st.markdown(
                f"<p style='font-size: 24px; font-weight: bold; color: #1E88E5;'>💬 Фраза: {task['phrase']}</p>",
                unsafe_allow_html=True)

            if n < total:
                if st.button("Следующее задание ➡️", key=f"go_{prefix}_{n + 1}", use_container_width=True):
                    st.session_state[state_key] = n + 1
                    st.rerun()
            else:
                mark_done(prefix)
                st.success(done_text)
                st.balloons()

            if n > 1:
                if st.button(f"⬅️ Вернуться к Заданию {n - 1}", key=f"back_{prefix}_{n - 1}",
                             use_container_width=True):
                    st.session_state[state_key] = n - 1
                    st.rerun()

        elif answer != PLACEHOLDER:
            st.error("❌ Oh, try another one!")

CITY_TASKS = [
    {"question": "At the ______, and they only have numbered candles",
     "options": ["Subway", "School", "Supermarket", "Street"], "correct": 2,
     "video": "supermarket.mp4", "phrase": "At the supermarket, and they only have numbered candles"},

    {"question": "Is there a ______ in town? (Послушай фразу из видео)",
     "options": ["Bank", "Hospital", "Park", "Cinema"], "correct": 0,
     "video": "bank.mp4", "phrase": "Is there a bank in the town?"},

    {"question": "Why aren't you at _______ helping Sunny?",
     "options": ["A hospital", "A cafe", "A bus", "A cinema"], "correct": 0,
     "video": "hospital.mp4", "phrase": "Why aren't you at the hospital helping Sunny?"},

    {"question": "They are on my ____. They can be your ______ too.",
     "options": ["Street", "Library", "Station", "Mall"], "correct": 1,
     "video": "1029.mp4", "phrase": "They are on my library. They can be your library too."},

    {"question": "Welcome to the ___.",
     "options": ["Bank", "Bookshop", "Match", "Park"], "correct": 3,
     "video": "park.mp4", "phrase": "Welcome to the park."},

    {"question": "They're part of the ________. They're known.",
     "options": ["Village", "Country", "Neighborhood", "Home"], "correct": 2,
     "video": "1.mp4", "phrase": "They're part of the neighborhood. They're known."},

    {"question": "And the scout may hope to learn that, say, there's a _____ in a convenient location across a river.",
     "options": ["Tunnel", "Bridge", "Taxi", "Road"], "correct": 1,
     "video": "1104.mp4",
     "phrase": "And the scout may hope to learn that, say, there's a bridge in a convenient location across a river."},

    {"question": "A man with a large nose and dark eyes was sitting on a grate in the _____.",
     "options": ["Driver", "Pedestrian", "Bike", "Sidewalk"], "correct": 3,
     "video": "1234.mp4",
     "phrase": "A man with a large nose and dark eyes was sitting on a grate in the sidewalk."},

    {"question": "Meet me at the _____ in the morning.",
     "options": ["Train station", "Office", "Airport", "School"], "correct": 2,
     "video": "1105.mp4", "phrase": "Meet me at the airport in the morning."},

    {"question": "Some countries are making all ____ _____ free in cities.",
     "options": ["Public transport", "Cars", "Food", "Houses"], "correct": 0,
     "video": "13.mp4", "phrase": "Some countries are making all public transport free in cities."},
]

FRUIT_TASKS = [
    {"question": "Baking ____ pie? Discount orange warehouse has you covered!",
     "options": ["Orange", "Milk", "Grapes", "Apple"], "correct": 3,
     "video": "1488.mp4", "phrase": "Baking apple pie? Discount orange warehouse has you covered!"},

    {"question": "Steal me the crown and all your dreams come true. Respect. Power. _____!",
     "options": ["Tomato", "Banana", "Meat", "Cucumber"], "correct": 1,
     "video": "1027.mp4",
     "phrase": "Minions: (gibberish sounds) ... \"Papa!\" <br>\"Steal me the crown and all your dreams come true. Respect. Power. Banana!\""},

    {"question": "Grapefruit, apple fruit, _____ fruit, carrot, vegetable.",
     "options": ["Watermelon", "Orange", "Bread", "Apple"], "correct": 1,
     "video": "orange.mp4", "phrase": "Grapefruit, apple fruit, orange fruit, carrot, vegetable."},

    {"question": "If you want to make a ____ jelly, for example...",
     "options": ["Orange", "Melon", "Pear", "Fish"], "correct": 2,
     "video": "1102.mp4", "phrase": "If you want to make a pear jelly, for example..."},

    {"question": "To make that strain some _____ juice.",
     "options": ["Grapes", "Lemon", "Cherry", "Peach"], "correct": 3,
     "video": "100.mp4", "phrase": "To make that strain some peach juice."},

    {"question": "This way it helps the apple cook evenly alongside the _____ in their little pot of doom.",
     "options": ["Mango", "Pineapple", "Strawberry", "Kiwi"], "correct": 0,
     "video": "1106.mp4",
     "phrase": "This way it helps the apple cook evenly alongside the mango in their little pot of doom."},

    {"question": "You should never ever put ____ on a pizza.",
     "options": ["Tomatoes", "Pomegranate", "Tomato", "Pineapple"], "correct": 3,
     "video": "14.mp4", "phrase": "You should never ever put pineapple on a pizza."},

    {"question": "I'm adding 3 tablespoons of _____ oil to a big old pot.",
     "options": ["Olive", "Coconut", "Sweet", "Vegetable"], "correct": 1,
     "video": "456.mp4", "phrase": "I'm adding 3 tablespoons of coconut oil to a big old pot."},

    {"question": "You know, the lemonade that's made from actual ____, and you have that beautiful scent of ____ oil?",
     "options": ["Apple/s", "Lime/s", "Lemon/s", "Orange/s"], "correct": 2,
     "video": "09.mp4",
     "phrase": "You know, the lemonade that's made from actual lemons, and you have that beautiful scent of lemon oil?"},

    {"question": "____ cacti grow on limestone soils in seasonally dry tropical forests.",
     "options": ["Melon", "Papaya", "Dragon fruit", "Apricot"], "correct": 0,
     "video": "1107.mp4",
     "phrase": "Melon cacti grow on limestone soils in seasonally dry tropical forests."},
]

FOOD_TASKS = [
    {"question": "I'd imagine ____, and probably like, in the summer.",
     "options": ["Toffee", "Coffee", "Copy", "Coat"], "correct": 1,
     "video": "1109.mp4", "phrase": "I'd imagine coffee, and probably like, in the summer."},

    {"question": "I'll leave you to explore the rest of the _____ by yourself.",
     "options": ["Money", "Movie", "Menu", "Map"], "correct": 2,
     "video": "45.mp4", "phrase": "I'll leave you to explore the rest of the menu by yourself."},

    {"question": "...his own troops went _____ and without pay.",
     "options": ["Bell", "Starving", "To war", "Hungry"], "correct": 3,
     "video": "78.mp4", "phrase": "...his own troops went hungry and without pay."},

    {"question": "When I was out to _____ with my friend the other day.",
     "options": ["Breakfast", "Break", "Lunch", "Fast"], "correct": 0,
     "video": "89.mp4", "phrase": "When I was out to breakfast with my friend the other day."},

    {"question": "I worked as a _____ at the Bath Theatre Royal.",
     "options": ["Water", "Driver", "Waiter", "Actor"], "correct": 2,
     "video": "97.mp4", "phrase": "I worked as a waiter at the Bath Theatre Royal."},

    {"question": "...which means less _____ fruit, veg, seeds and nuts.",
     "options": ["Tasty", "Delicious", "Heavy", "Different"], "correct": 1,
     "video": "0.mp4", "phrase": "...which means less delicious fruit, veg, seeds and nuts."},

    {"question": "At the end of each day, I made a huge pot of _____.",
     "options": ["Meal", "Soul", "Rice", "Soup"], "correct": 3,
     "video": "12.mp4", "phrase": "At the end of each day, I made a huge pot of soup."},

    {"question": "They're really good as a ____ with some custard.",
     "options": ["Dress", "Bun", "Dessert", "Desk"], "correct": 2,
     "video": "90.mp4", "phrase": "They're really good as a dessert with some custard."},

    {"question": "Walking, eating your favorite food, or drinking a cup of ____ can all be mindful activities.",
     "options": ["Tea", "Coffee", "Team", "Ten"], "correct": 0,
     "video": "40.mp4",
     "phrase": "Walking, eating your favorite food, or drinking a cup of tea can all be mindful activities."},

    {"question": "You could use a whisk but I'm going to use a wooden _____.",
     "options": ["Moon", "Spoon", "Fork", "Plate"], "correct": 1,
     "video": "18.mp4", "phrase": "You could use a whisk but I'm going to use a wooden spoon."},
]

IDIOM_TASKS = [
    {"question": "...and we're shot so enough filming let's _______.",
     "options": ["Ударить мешок", "Пойти за покупками", "Сильно устать", "Пойти спать"], "correct": 3,
     "video": "1115.mp4", "phrase": "...and we're shot so enough filming let's hit the sack."},

    {"question": "...to ______ about his affair with Princess Diana.",
     "options": ["Рассыпать бобы", "Приготовить обед", "Выдать секрет", "Потерять деньги"], "correct": 2,
     "video": "890.mp4", "phrase": "...to spill the beans about his affair with Princess Diana."},

    {"question": "Sure, every _______",
     "options": ["Очень редко", "Под голубой луной", "Каждую ночь", "Очень поздно"], "correct": 0,
     "video": "23.mp4", "phrase": "Sure, every once in a blue moon."},

    {"question": "Oh, it'll happen ______",
     "options": ["Очень скоро", "Когда потеплеет", "Никогда (когда рак на горе свистнет)", "Когда будет урожай"],
     "correct": 2,
     "video": "56.mp4", "phrase": "Oh, it'll happen when pigs fly."},

    {"question": "'_______, in a pickle' -- all from Shakespeare.",
     "options": ["Разбить лёд", "Разрядить обстановку, начать общение", "Замёрзнуть", "Поссориться"], "correct": 1,
     "video": "1118.mp4", "phrase": "'Break the ice, in a pickle' -- all from Shakespeare."},

    {"question": "RAINN WILSON: Anything else, or should we would _______?",
     "options": ["Назвать день", "Взять выходной на неделю", "Начать новый день", "Закончить работу на сегодня"],
     "correct": 3,
     "video": "41.mp4", "phrase": "RAINN WILSON: Anything else, or should we would call it a day?"},

    {"question": "The ball is in ______",
     "options": ["Теперь твоя очередь действовать", "Мяч на твоём корте", "Ты проиграл", "Играй в теннис лучше"],
     "correct": 0,
     "video": "w.mp4", "phrase": "The ball is in your court."},

    {"question": "It’s __________",
     "options": ["Кошки и собаки падают с неба", "Идёт снег", "Льёт как из ведра", "Очень холодно"], "correct": 2,
     "video": "1120.mp4", "phrase": "It’s raining cats and dogs."},

    {"question": "We were not ______.",
     "options": ["Сидеть рядом", "На одной странице", "Читать одну книгу", "Понимать друг друга, быть согласными"],
     "correct": 3,
     "video": "28.mp4", "phrase": "We were not on the same page."},

    {"question": "This was ______ for some in Thailand.",
     "options": ["Последняя соломинка", "Последняя капля", "Самый лёгкий путь", "Конец лета"], "correct": 1,
     "video": "38.mp4", "phrase": "This was the last straw for some in Thailand."},
]

st.sidebar.title("🚀 Программа обучения")

# Память для меню
if "menu_choice" not in st.session_state:
    st.session_state.menu_choice = "Главная"

if st.sidebar.button("🏠 Главная", use_container_width=True):
    st.session_state.menu_choice = "Главная"
if st.sidebar.button("📖 Мой словарь", use_container_width=True):
    st.session_state.menu_choice = "Мой словарь"

st.sidebar.write("---")

with st.sidebar.expander("📊 Уровень A1-A2 (Начальный)", expanded=False):
    if st.button(menu_label("🏙️ Город", "city"), key="menu_city", use_container_width=True):
        st.session_state.menu_choice = "🏙️ Город"
    if st.button(menu_label("🍎 Фрукты", "fruit"), key="menu_fruits", use_container_width=True):
        st.session_state.menu_choice = "🍎 Фрукты"
    if st.button(menu_label("🍽️ Еда и кафе", "food"), key="menu_food", use_container_width=True):
        st.session_state.menu_choice = "🍽️ Еда и кафе"

with st.sidebar.expander("🧠 Уровень B1-B2 (Средний)", expanded=False):
    if st.button(menu_label("🌟 Слово дня (Идиомы)", "idiom"), key="menu_idioms", use_container_width=True):
        st.session_state.menu_choice = "🌟 Слово дня (Идиомы)"

choice = st.session_state.menu_choice

if choice == "Главная":
    st.markdown("<h1 style='text-align: center; color: #1E88E5;'>🎬 Welcome to Prince English!</h1>",
                unsafe_allow_html=True)
    st.markdown(
        "<h3 style='text-align: center; font-weight: normal; color: #555555;'>Твой интерактивный тренажер живого английского языка по фильмам и сериалам, подкастам.</h3>",
        unsafe_allow_html=True)
    st.write(" ")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("""
        <div style='background-color: #F0F4F8; padding: 20px; border-radius: 10px; border-left: 5px solid #1E88E5;'>
            <h4 style='color: #1E88E5; margin-top: 0;'>🌟 Слово дня: A piece of cake</h4>
            <p style='font-size: 18px; margin-bottom: 5px;'><b>Дословный перевод:</b> Кусок пирога</p>
            <p style='font-size: 18px; margin-bottom: 5px;'><b>Реальное значение:</b> Проще простого / Пара пустяков</p>
            <p style='font-size: 16px; color: #666; font-style: italic;'>Пример: "This English test was a piece of cake!" (Этот тест по английскому был проще простого!)</p>
        </div>
        """, unsafe_allow_html=True)

        st.write(" ")

        st.markdown("<h4 style='color: #333;'>💡 Как учиться эффективно?</h4>", unsafe_allow_html=True)
        st.markdown("""
        * **Слушай интонации:** В коротких видеороликах актеры говорят так, как люди общаются в реальной жизни. Обращай внимание на ударения!
        * **Повторяй вслух:** Как только угадал слово и посмотрел видео, попробуй скопировать произношение персонажа (shadowing).
        * **Заглядывай в словарь:** Не забывай повторять пройденные слова, чтобы они закрепились в памяти.
        """)

    with col2:
        st.markdown("<h4 style='color: #333;'>🎯 Твои цели на сегодня</h4>", unsafe_allow_html=True)

        task1 = st.checkbox("Разобрать раздел 'Город'")
        task2 = st.checkbox("Выучить фразу Миньонов про Banana")
        task3 = st.checkbox("Повторить слова в словаре")

        completed = sum([task1, task2, task3])
        if completed == 0:
            st.info("Выполняй цели, чтобы заполнить шкалу! 🚀")
        elif completed == 1:
            st.warning("Начало положено! Еще чуть-чуть. 📈")
        elif completed == 2:
            st.warning("Отличный темп! Осталась одна цель. 🔥")
        elif completed == 3:
            st.success("🎉 Все цели на сегодня выполнены! Ты супер!")
            st.balloons()

    st.write("---")
    st.markdown("<p style='text-align: center; color: #888;'>👈 Выбери тему в меню слева, чтобы начать тренировку!</p>",
                unsafe_allow_html=True)


elif choice == "🏙️ Город":
    st.title("🏙️ Раздел: Город")
    run_quiz("city", CITY_TASKS,
             "🏆 Молодец! Ты прошел весь раздел 'Город'. Теперь можешь двигаться дальше!")


elif choice == "🍎 Фрукты":
    st.title("🍎 Раздел: Фрукты")
    run_quiz("fruit", FRUIT_TASKS,
             "🏆 Молодец! Ты выполнил раздел 'Фрукты'. Теперь можешь двигаться дальше!")


elif choice == "🍽️ Еда и кафе":
    st.title("🍽️ Раздел: Еда и кафе")
    run_quiz("food", FOOD_TASKS,
             "🏆 Молодец! Ты выполнил раздел 'Еда и кафе'!")


elif choice == "🌟 Слово дня (Идиомы)":
    st.title("🌟 Раздел: Слово дня (Идиомы)")
    run_quiz("idiom", IDIOM_TASKS,
             "🏆 Молодец! Ты выполнил раздел 'Слово дня (Идиомы)'!")


elif choice == "Мой словарь":
    st.title("📖 Умный словарь")

    side_left, center_col, side_right = st.columns([1, 4, 1])

    with center_col:
        st.markdown("<h3 style='color: #1E88E5;'>➕ Добавить слово</h3>", unsafe_allow_html=True)

        new_word = st.text_input("Введите слово на английском (например, Gorgeous):", key="new_eng")

        for k in ["ai_translation", "ai_example_eng", "ai_example_rus", "ai_word", "ai_source"]:
            if k not in st.session_state:
                st.session_state[k] = ""

        if st.button("🤖 Сгенерировать перевод и пример", use_container_width=True):
            if new_word.strip() != "":
                with st.spinner("DeepSeek подбирает перевод и пример... 🧠"):
                    try:
                        translation, ex_eng, ex_rus, source = get_card(new_word.strip())
                        st.session_state.ai_translation = translation
                        st.session_state.ai_example_eng = ex_eng
                        st.session_state.ai_example_rus = ex_rus
                        st.session_state.ai_source = source
                        st.session_state.ai_word = new_word.strip()
                    except Exception as e:
                        st.error(f"Не удалось получить перевод: {e}. Проверьте интернет и попробуйте ещё раз.")
            else:
                st.error("❌ Сначала введите английское слово!")

        if st.session_state.ai_translation:
            st.write("---")
            st.markdown(f"<b>Слово:</b> {html.escape(st.session_state.ai_word)}", unsafe_allow_html=True)
            st.markdown(f"<b>Перевод слова:</b> {html.escape(st.session_state.ai_translation)}",
                        unsafe_allow_html=True)
            st.markdown(f"<b>🇬🇧 Пример:</b> {html.escape(st.session_state.ai_example_eng)}",
                        unsafe_allow_html=True)
            st.markdown(f"<b>🇷🇺 Перевод примера:</b> {html.escape(st.session_state.ai_example_rus)}",
                        unsafe_allow_html=True)
            st.caption(f"Источник: {st.session_state.ai_source}")

            if st.button("📥 Сохранить эту карточку в словарь", use_container_width=True):
                cursor.execute(
                    "INSERT INTO words (english_word, russian_translation, example_eng, example_rus) VALUES (?, ?, ?, ?)",
                    (st.session_state.ai_word, st.session_state.ai_translation,
                     st.session_state.ai_example_eng, st.session_state.ai_example_rus)
                )
                conn.commit()
                for k in ["ai_translation", "ai_example_eng", "ai_example_rus", "ai_word", "ai_source"]:
                    st.session_state[k] = ""
                st.success("🎉 Карточка успешно сохранена!")
                st.rerun()

        st.write("---")
        st.markdown("<h3>📚 Твоя личная база выученных слов</h3>", unsafe_allow_html=True)

        cursor.execute("SELECT english_word, russian_translation, example_eng, example_rus FROM words ORDER BY id DESC")
        saved_words = cursor.fetchall()

        if not saved_words:
            st.info("Твой словарь пока пуст. Добавь свое первое слово выше! 🚀")
        else:
            for index, (eng, rus, ex_e, ex_r) in enumerate(saved_words, 1):
                st.markdown(
                    f"<p style='margin-bottom: 2px;'><b>{index}. {html.escape(eng)}</b> — {html.escape(rus)}</p>",
                    unsafe_allow_html=True)
                if ex_e:
                    st.markdown(
                        f"<p style='font-size: 18px; color: #666; margin-left: 20px; margin-top: 0; margin-bottom: 10px;'><i>💡 {html.escape(ex_e)} ({html.escape(ex_r or '')})</i></p>",
                        unsafe_allow_html=True)
