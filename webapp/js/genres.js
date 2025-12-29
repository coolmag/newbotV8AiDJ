export const MENU_ROOT = {
    name: "Главное меню",
    type: "root",
    children: [
        { 
            id: "g_for", 
            name: "🌍 Зарубежная музыка", 
            type: "category",
            children: [
                {
                    name: "💃 Поп & Ретро",
                    children: [
                        { name: "Свежие хиты 2024", query: "top pop hits 2024" },
                        { name: "2000-е (MTV Hits)", query: "2000s pop hits britney spears rihanna" },
                        { name: "90-е (Eurodance)", query: "90s pop hits spice girls backstreet boys" },
                        { name: "80-е (Disco)", query: "best 80s pop hits michael jackson" }
                    ]
                },
                {
                    name: "🎸 Рок & Метал",
                    children: [
                        { name: "Classic Rock (70s)", query: "classic rock 70s led zeppelin" },
                        { name: "Hard & Glam (80s)", query: "80s hard rock guns n roses" },
                        { name: "Grunge (90s)", query: "90s grunge nirvana pearl jam" },
                        { name: "Indie Rock", query: "indie rock arctic monkeys" },
                        { name: "Heavy Metal", query: "best heavy metal metallica" },
                        { name: "Punk Rock", query: "punk rock green day blink 182" }
                    ]
                },
                {
                    name: "🎤 Хип-хоп",
                    children: [
                        { name: "Trap & Modern", query: "modern trap hip hop drake" },
                        { name: "Eminem & 2000s", query: "2000s hip hop eminem 50 cent" },
                        { name: "Old School (90s)", query: "90s hip hop tupac biggie" },
                        { name: "Lofi & Chill", query: "lofi hip hop radio" }
                    ]
                },
                {
                    name: "🎧 Электроника",
                    children: [
                        { name: "Phonk", query: "drift phonk mix" },
                        { name: "House", query: "ibiza house music" },
                        { name: "Techno", query: "techno bunker mix" },
                        { name: "DnB", query: "liquid drum and bass mix" },
                        { name: "Synthwave", query: "synthwave retrowave mix" }
                    ]
                }
            ]
        },
        { 
            id: "g_ru", 
            name: "🇷🇺 Русская музыка", 
            type: "category", 
            children: [
                {
                    name: "💃 Русская Попса",
                    children: [
                        { name: "Топ чарты 2024", query: "русские хиты 2024 новинки" },
                        { name: "Нулевые", query: "русские хиты 2000х" },
                        { name: "Лихие 90-е", query: "русская дискотека 90 руки вверх" }
                    ]
                },
                {
                    name: "🎸 Русский Рок",
                    children: [
                        { name: "Легенды (Кино, Би-2)", query: "русский рок хиты кино би-2" },
                        { name: "Король и Шут", query: "король и шут лучшее" },
                        { name: "Современный", query: "современный русский рок" }
                    ]
                },
                {
                    name: "🎤 Русский Рэп",
                    children: [
                        { name: "Кальянный / Лирика", query: "кальянный рэп мияги" },
                        { name: "Новая Школа", query: "русский рэп новинки моргенштерн" },
                        { name: "Олдскул (Баста, Гуф)", query: "русский рэп 2000х баста" }
                    ]
                },
                {
                    name: "☭ СССР & Ретро",
                    children: [
                        { name: "Золотые хиты СССР", query: "лучшие песни ссср 70-80" },
                        { name: "Кинофильмы", query: "песни из советских кинофильмов" },
                        { name: "Высоцкий", query: "владимир высоцкий лучшие песни" }
                    ]
                },
                { name: "🚬 Шансон", query: "золотой шансон михаил круг" }
            ]
        },
        { 
            id: "moods", 
            name: "✨ Под настроение", 
            type: "category",
            children: [
                { name: "🚗 В машину (Phonk/Bass)", query: "night drive music bass boosted" },
                { name: "💪 Спорт / Gym", query: "workout motivation music" },
                { name: "👨‍💻 Работа / Фокус", query: "deep focus music for work" },
                { name: "🎉 Вечеринка", query: "party mix 2024 club dance" },
                { name: "😌 Релакс / Сон", query: "ambient relaxing music for sleep" },
                { name: "🎻 Классика", query: "best classical music mozart" }
            ]
        },
        { 
            id: "random", 
            name: "🎲 Мне повезет", 
            type: "action",
            action: "random"
        }
    ]
};