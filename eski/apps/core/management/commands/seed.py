from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.bootstrap import ensure_platform_admins
from apps.assessments.models import Question, Test, TestAttempt, TestSection
from apps.attendance.models import Attendance
from apps.core.services import grade_attempt
from apps.groups.models import Enrollment, Group, Language
from apps.homework.models import Assignment, AssignmentItem, Submission
from apps.practice.models import Exercise, ExerciseAttempt


LANGUAGES = [
    ("en", "Английский", "English", "🇬🇧"),
    ("de", "Немецкий", "Deutsch", "🇩🇪"),
    ("fr", "Французский", "Français", "🇫🇷"),
    ("es", "Испанский", "Español", "🇪🇸"),
    ("it", "Итальянский", "Italiano", "🇮🇹"),
    ("zh", "Китайский", "中文", "🇨🇳"),
    ("ja", "Японский", "日本語", "🇯🇵"),
    ("ko", "Корейский", "한국어", "🇰🇷"),
    ("ar", "Арабский", "العربية", "🇸🇦"),
    ("tr", "Турецкий", "Türkçe", "🇹🇷"),
    ("ru", "Русский", "Русский", "🇷🇺"),
]


class Command(BaseCommand):
    help = "Создаёт демонстрационные данные DiplomacyLC"

    def add_arguments(self, parser):
        parser.add_argument("--skip-if-exists", action="store_true")

    def handle(self, *args, **options):
        if options.get("skip_if_exists") and User.objects.filter(login="t.sokolova").exists():
            self.stdout.write("Seed уже выполнен.")
            return

        langs = {}
        for code, name, native, flag in LANGUAGES:
            langs[code], _ = Language.objects.get_or_create(
                code=code, defaults={"name": name, "native_name": native, "flag": flag}
            )

        primary, secondary = ensure_platform_admins()

        teachers_spec = [
            ("t.ivanova", "Мария", "Иванова", "Teacher123!"),
            ("t.orlov", "Павел", "Орлов", "Teacher123!"),
            ("t.kim", "Елена", "Ким", "Teacher123!"),
        ]
        teachers = []
        for login, first, last, password in teachers_spec:
            user, _ = User.objects.get_or_create(
                login=login,
                defaults={"first_name": first, "last_name": last, "role": User.Role.TEACHER, "profile_completed": True},
            )
            user.set_password(password)
            user.role = User.Role.TEACHER
            user.profile_completed = True
            user.must_change_password = False
            user.save()
            teachers.append(user)

        ru_teachers_spec = [
            ("t.sokolova", "Анна", "Соколова", "Игоревна", "Sokolova1!"),
            ("t.volkov", "Дмитрий", "Волков", "Сергеевич", "Volkov1!"),
            ("t.morozova", "Елена", "Морозова", "Викторовна", "Morozova1!"),
            ("t.kuznetsov", "Игорь", "Кузнецов", "Петрович", "Kuznetsov1!"),
        ]
        ru_teachers = []
        for login, first, last, middle, password in ru_teachers_spec:
            user, _ = User.objects.get_or_create(
                login=login,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "middle_name": middle,
                    "role": User.Role.TEACHER,
                    "profile_completed": True,
                },
            )
            user.first_name = first
            user.last_name = last
            user.middle_name = middle
            user.set_password(password)
            user.role = User.Role.TEACHER
            user.profile_completed = True
            user.must_change_password = False
            user.save()
            ru_teachers.append(user)

        for extra_login in ("t.lebedeva", "t.novikov", "t.pavlov", "t.frolova", "t.egorov"):
            extra = User.objects.filter(login=extra_login).first()
            if extra:
                extra.is_active = False
                extra.save(update_fields=["is_active"])

        ru_assistants_spec = [
            ("a.krylova", "Полина", "Крылова", ru_teachers[0]),
            ("a.belov", "Иван", "Белов", ru_teachers[1]),
            ("a.orlova", "Мария", "Орлова", ru_teachers[2]),
            ("a.sergeeva", "Алина", "Сергеева", ru_teachers[3]),
        ]
        for login, first, last, teacher in ru_assistants_spec:
            user, _ = User.objects.get_or_create(
                login=login,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "role": User.Role.ASSISTANT,
                    "lead_teacher": teacher,
                    "profile_completed": True,
                },
            )
            user.first_name = first
            user.last_name = last
            user.role = User.Role.ASSISTANT
            user.lead_teacher = teacher
            user.profile_completed = True
            user.must_change_password = False
            user.is_active = True
            user.set_password("Assist123!")
            user.save()

        students_spec = [
            ("s.petrov", "Илья", "Петров"),
            ("s.smirnova", "Алина", "Смирнова"),
            ("s.nazarov", "Тимур", "Назаров"),
            ("s.belova", "Дарья", "Белова"),
            ("s.volkov", "Артём", "Волков"),
            ("s.moroz", "София", "Мороз"),
            ("s.lee", "Мина", "Ли"),
            ("s.karim", "Амир", "Каримов"),
            ("s.novik", "Егор", "Новиков"),
            ("s.rakhim", "Айгерим", "Рахимова"),
            ("s.frost", "Ника", "Морозова"),
            ("s.park", "Джин", "Пак"),
        ]
        students = []
        for login, first, last in students_spec:
            user, _ = User.objects.get_or_create(
                login=login,
                defaults={"first_name": first, "last_name": last, "role": User.Role.STUDENT},
            )
            user.set_password("Student123!")
            user.role = User.Role.STUDENT
            user.profile_completed = True
            user.must_change_password = False
            user.save()
            students.append(user)

        groups_spec = [
            ("B1 Evening English", "en", teachers[0], "B1", "Вт / Чт 18:30", "204"),
            ("A2 German", "de", teachers[1], "A2", "Пн / Ср 17:00", "110"),
            ("B2 French Conversation", "fr", teachers[0], "B2", "Сб 11:00", "301"),
            ("A1 Spanish Kids+", "es", teachers[2], "A1", "Сб 09:30", "012"),
            ("B1 Korean", "ko", teachers[2], "B1", "Пт 19:00", "215"),
            ("B1 Русский как иностранный", "ru", teachers[0], "B1", "Пн / Ср 19:00", "118"),
        ]
        groups = []
        for name, lang, teacher, level, schedule, room in groups_spec:
            group, _ = Group.objects.get_or_create(
                name=name,
                defaults={
                    "language": langs[lang],
                    "teacher": teacher,
                    "level": level,
                    "schedule": schedule,
                    "room": room,
                },
            )
            group.teacher = teacher
            group.language = langs[lang]
            group.save()
            groups.append(group)

        ru_levels = ["A1", "A2", "B1", "B2"]
        ru_schedules = [
            "Пн / Ср 09:00",
            "Вт / Чт 11:00",
            "Пн / Ср 16:00",
            "Вт / Чт 18:30",
        ]
        for group in Group.objects.filter(language=langs["ru"]):
            if group.name.startswith("Русский ") and "группа" not in group.name:
                group.is_active = False
                group.save(update_fields=["is_active"])
        ru_groups = []
        for teacher_index, teacher in enumerate(ru_teachers):
            for slot, (level, schedule) in enumerate(zip(ru_levels, ru_schedules), start=1):
                name = f"Русский {level} · {teacher.last_name} · группа {slot}"
                group, _ = Group.objects.get_or_create(
                    name=name,
                    defaults={
                        "language": langs["ru"],
                        "teacher": teacher,
                        "level": level,
                        "schedule": schedule,
                        "room": str(200 + teacher_index * 4 + slot),
                    },
                )
                group.teacher = teacher
                group.language = langs["ru"]
                group.level = level
                group.schedule = schedule
                group.is_active = True
                group.save()
                ru_groups.append(group)

        ru_students = []
        for index, group in enumerate(ru_groups, start=1):
            login = f"s.ru{index:02d}"
            user, _ = User.objects.get_or_create(
                login=login,
                defaults={
                    "first_name": "",
                    "last_name": "",
                    "role": User.Role.STUDENT,
                    "must_change_password": True,
                    "profile_completed": False,
                },
            )
            user.set_password("Student123!")
            user.role = User.Role.STUDENT
            user.must_change_password = True
            user.profile_completed = False
            user.is_active = True
            user.save()
            ru_students.append(user)
            Enrollment.objects.filter(student=user).exclude(group=group).delete()
            Enrollment.objects.get_or_create(group=group, student=user)

        chunks = [
            students[0:5],
            students[3:8],
            students[6:10],
            students[8:12],
            students[1:4] + students[10:12],
            students[0:3] + students[8:10],
        ]
        for group, members in zip(groups, chunks):
            for student in members:
                Enrollment.objects.get_or_create(group=group, student=student)

        today = timezone.localdate()
        for group in groups:
            members = [item.student for item in group.enrollments.select_related("student")]
            for days in range(1, 8):
                lesson = today - timedelta(days=days)
                for index, student in enumerate(members):
                    status = Attendance.Status.PRESENT if index % 5 else Attendance.Status.ABSENT
                    Attendance.objects.update_or_create(
                        student=student,
                        group=group,
                        lesson_date=lesson,
                        defaults={"status": status, "marked_by": group.teacher},
                    )

        assignment, _ = Assignment.objects.get_or_create(
            title="Present Perfect: дневник недели",
            group=groups[0],
            defaults={
                "description": "Напишите 10 предложений о том, что вы уже сделали на этой неделе. Прикрепите голосовой файл по желанию.",
                "deadline": timezone.now() + timedelta(days=3),
                "created_by": teachers[0],
            },
        )
        AssignmentItem.objects.get_or_create(
            assignment=assignment,
            order=1,
            defaults={"prompt": "Перечислите 5 маркеров Present Perfect и приведите пример."},
        )
        submission, _ = Submission.objects.get_or_create(
            assignment=assignment,
            student=students[0],
            defaults={
                "answer": "I have finished my homework. I have watched two episodes in English.",
                "status": Submission.Status.SUBMITTED,
                "submitted_at": timezone.now(),
            },
        )

        test, _ = Test.objects.get_or_create(
            title="English B1 Checkpoint",
            group=groups[0],
            defaults={"description": "Промежуточный срез: лексика и грамматика.", "created_by": teachers[0]},
        )
        Question.objects.get_or_create(
            test=test,
            order=1,
            defaults={
                "type": Question.Type.SINGLE,
                "question_text": "Выберите правильный перевод: apple",
                "payload": {"options": ["яблоко", "стол", "окно"], "correct": "яблоко"},
                "points": 1,
            },
        )
        Question.objects.get_or_create(
            test=test,
            order=2,
            defaults={
                "type": Question.Type.MULTIPLE,
                "question_text": "Какие времена относятся к прошедшему?",
                "payload": {
                    "options": ["Past Simple", "Present Perfect", "Future Simple", "Past Continuous"],
                    "correct": ["Past Simple", "Present Perfect", "Past Continuous"],
                },
                "points": 2,
            },
        )
        Question.objects.get_or_create(
            test=test,
            order=3,
            defaults={
                "type": Question.Type.FILL_BLANK,
                "question_text": "She ____ already left.",
                "payload": {"correct": ["has", "Has"]},
                "points": 1,
            },
        )
        Question.objects.get_or_create(
            test=test,
            order=4,
            defaults={
                "type": Question.Type.MATCH,
                "question_text": "Соедините слово и перевод",
                "payload": {
                    "left": ["cat", "house", "book"],
                    "right": ["кот", "дом", "книга"],
                    "correct": {"cat": "кот", "house": "дом", "book": "книга"},
                },
                "points": 3,
            },
        )
        Question.objects.get_or_create(
            test=test,
            order=5,
            defaults={
                "type": Question.Type.TEXT,
                "question_text": "Опишите свой обычный учебный день на английском (5–7 предложений).",
                "payload": {},
                "points": 3,
            },
        )
        attempt, _ = TestAttempt.objects.get_or_create(test=test, student=students[1])
        if attempt.status != TestAttempt.Status.GRADED:
            grade_attempt(
                attempt,
                {
                    str(test.questions.get(order=1).id): "яблоко",
                    str(test.questions.get(order=2).id): ["Past Simple", "Present Perfect", "Past Continuous"],
                    str(test.questions.get(order=3).id): "has",
                    str(test.questions.get(order=4).id): {"cat": "кот", "house": "дом", "book": "книга"},
                    str(test.questions.get(order=5).id): "I wake up, study English and go to DipLC.",
                },
            )

        ielts, _ = Test.objects.get_or_create(
            title="IELTS Reading: Language Cafés",
            group=groups[0],
            defaults={
                "kind": Test.Kind.READING,
                "description": "Academic Reading, Passage 1.",
                "instructions": "You should spend about 20 minutes on this passage. Choose TRUE if the statement agrees with the text, FALSE if it contradicts it, and NOT GIVEN if there is no information.",
                "time_limit_minutes": 20,
                "created_by": teachers[0],
            },
        )
        passage, _ = TestSection.objects.get_or_create(
            test=ielts,
            order=1,
            defaults={
                "title": "Passage 1",
                "kind": TestSection.Kind.PASSAGE,
                "body": (
                    "Every Saturday DipLC opens a language café in the city centre. Students bring snacks "
                    "and speak only in the language they study. Teachers do not correct every mistake: "
                    "the aim is fluency, not a grammar test. Since 2019 the café has welcomed more than "
                    "two thousand visitors. Some guests come only once, while others return each week "
                    "and later join regular evening courses."
                ),
            },
        )
        Question.objects.get_or_create(
            test=ielts,
            order=1,
            defaults={
                "section": passage,
                "type": Question.Type.TFNG,
                "question_text": "Teachers correct every grammar mistake at the café.",
                "payload": {"correct": "false"},
                "points": 1,
            },
        )
        Question.objects.get_or_create(
            test=ielts,
            order=2,
            defaults={
                "section": passage,
                "type": Question.Type.TFNG,
                "question_text": "The café opened in 2019.",
                "payload": {"correct": "not_given"},
                "points": 1,
            },
        )
        Question.objects.get_or_create(
            test=ielts,
            order=3,
            defaults={
                "section": passage,
                "type": Question.Type.FILL_BLANK,
                "question_text": "Complete the sentences. Write NO MORE THAN TWO WORDS AND/OR A NUMBER.",
                "payload": {
                    "items": [
                        {"prompt": "The café takes place every ____.", "correct": ["Saturday"]},
                        {"prompt": "It has welcomed more than ____ visitors.", "correct": ["2000", "two thousand", "2,000"]},
                    ]
                },
                "points": 2,
            },
        )
        Question.objects.get_or_create(
            test=ielts,
            order=4,
            defaults={
                "section": passage,
                "type": Question.Type.SINGLE,
                "question_text": "What is the main aim of the café?",
                "payload": {
                    "options": ["to test grammar", "to build fluency", "to sell snacks"],
                    "correct": "to build fluency",
                },
                "points": 1,
            },
        )

        listening, _ = Test.objects.get_or_create(
            title="IELTS Listening: Weekend Club Booking",
            group=groups[0],
            defaults={
                "kind": Test.Kind.LISTENING,
                "description": "Section 1. Form completion.",
                "instructions": "You will hear a student booking a weekend conversation club. Complete the form. Write ONE WORD AND/OR A NUMBER for each answer.",
                "time_limit_minutes": 10,
                "created_by": teachers[0],
            },
        )
        section1, _ = TestSection.objects.get_or_create(
            test=listening,
            order=1,
            defaults={
                "title": "Section 1",
                "kind": TestSection.Kind.AUDIO,
                "body": "A student phones DipLC to book a weekend conversation club.",
            },
        )
        Question.objects.get_or_create(
            test=listening,
            order=1,
            defaults={
                "section": section1,
                "type": Question.Type.FILL_BLANK,
                "question_text": "Questions 1–8\nComplete the form below.\nWrite ONE WORD AND/OR A NUMBER for each answer.",
                "payload": {
                    "layout": "notes",
                    "title": "Weekend Conversation Club",
                    "body": (
                        "Weekend Conversation Club\n\n"
                        "## Booking\n"
                        "* Start date: {1}\n"
                        "* Language: {2}\n"
                        "* Level: {3}\n"
                        "## Student details\n"
                        "* Family name: {4}\n"
                        "* Occupation: {5}\n"
                        "* Dietary request: no {6}\n"
                        "## Extra\n"
                        "* Heard about us from a {7}\n"
                        "* Please reserve {8} if possible\n"
                    ),
                    "items": [
                        {"n": 1, "prompt": "Q1", "correct": ["18 July", "18th July", "July 18"]},
                        {"n": 2, "prompt": "Q2", "correct": ["Spanish"]},
                        {"n": 3, "prompt": "Q3", "correct": ["B1"]},
                        {"n": 4, "prompt": "Q4", "correct": ["Karimova"]},
                        {"n": 5, "prompt": "Q5", "correct": ["engineer"]},
                        {"n": 6, "prompt": "Q6", "correct": ["fish"]},
                        {"n": 7, "prompt": "Q7", "correct": ["magazine"]},
                        {"n": 8, "prompt": "Q8", "correct": ["parking"]},
                    ],
                },
                "points": 8,
            },
        )

        goethe, _ = Test.objects.get_or_create(
            title="Goethe Lesen: Im Sprachcafé",
            group=groups[1],
            defaults={
                "kind": Test.Kind.READING,
                "instructions": "Lesen Sie den Text. Sind die Aussagen richtig, falsch oder steht das nicht im Text?",
                "time_limit_minutes": 20,
                "created_by": teachers[1],
            },
        )
        teil, _ = TestSection.objects.get_or_create(
            test=goethe,
            order=1,
            defaults={
                "title": "Teil 1",
                "kind": TestSection.Kind.PASSAGE,
                "body": "Jeden Samstag öffnet DipLC ein Sprachcafé. Die Gäste sprechen nur die Sprache, die sie lernen. Lehrer korrigieren nicht jeden Fehler.",
            },
        )
        Question.objects.get_or_create(
            test=goethe,
            order=1,
            defaults={
                "section": teil,
                "type": Question.Type.TFNG,
                "question_text": "Lehrer korrigieren jeden Fehler.",
                "payload": {"correct": "false"},
            },
        )

        delf, _ = Test.objects.get_or_create(
            title="DELF Compréhension: Le café des langues",
            group=groups[2],
            defaults={
                "kind": Test.Kind.READING,
                "instructions": "Lisez le document. Répondez par Vrai, Faux ou Non mentionné.",
                "time_limit_minutes": 20,
                "created_by": teachers[0],
            },
        )
        doc, _ = TestSection.objects.get_or_create(
            test=delf,
            order=1,
            defaults={
                "title": "Document 1",
                "kind": TestSection.Kind.PASSAGE,
                "body": "Chaque samedi, DipLC ouvre un café des langues. Les étudiants parlent uniquement la langue qu'ils étudient.",
            },
        )
        Question.objects.get_or_create(
            test=delf,
            order=1,
            defaults={
                "section": doc,
                "type": Question.Type.TFNG,
                "question_text": "Le café a lieu le dimanche.",
                "payload": {"correct": "false"},
            },
        )

        trki, _ = Test.objects.get_or_create(
            title="ТРКИ. Чтение: Языковое кафе",
            group=groups[5],
            defaults={
                "kind": Test.Kind.READING,
                "instructions": "Прочитайте текст. Отметьте: верно, неверно или в тексте не сказано.",
                "time_limit_minutes": 20,
                "created_by": teachers[0],
            },
        )
        tekst, _ = TestSection.objects.get_or_create(
            test=trki,
            order=1,
            defaults={
                "title": "Текст 1",
                "kind": TestSection.Kind.PASSAGE,
                "body": (
                    "Каждую субботу центр DipLC открывает языковое кафе. Гости приносят угощение "
                    "и говорят только на том языке, который изучают. Преподаватели не исправляют "
                    "каждую ошибку: важна беглость речи, а не грамматический зачёт."
                ),
            },
        )
        Question.objects.get_or_create(
            test=trki,
            order=1,
            defaults={
                "section": tekst,
                "type": Question.Type.TFNG,
                "question_text": "Преподаватели исправляют каждую ошибку.",
                "payload": {"correct": "false"},
            },
        )
        Question.objects.get_or_create(
            test=trki,
            order=2,
            defaults={
                "section": tekst,
                "type": Question.Type.FILL_BLANK,
                "question_text": "Дополните предложения. Не больше трёх слов.",
                "payload": {
                    "items": [
                        {"prompt": "Кафе работает каждую ____.", "correct": ["субботу"]},
                        {"prompt": "Для преподавателей важна ____ речи.", "correct": ["беглость"]},
                    ]
                },
                "points": 2,
            },
        )

        exercises = [
            {
                "title": "Vocabulary: Food",
                "language": langs["en"],
                "type": Exercise.Type.VOCABULARY,
                "prompt": "Выберите правильный перевод слова bread.",
                "content": {"options": ["хлеб", "сыр", "вода", "мясо"], "correct": "хлеб"},
                "level": "A2",
            },
            {
                "title": "Matching: Daily routine",
                "language": langs["en"],
                "type": Exercise.Type.MATCHING,
                "prompt": "Соедините глагол и перевод.",
                "content": {
                    "pairs": [["wake up", "просыпаться"], ["have lunch", "обедать"], ["go to bed", "ложиться спать"]],
                    "correct": {"wake up": "просыпаться", "have lunch": "обедать", "go to bed": "ложиться спать"},
                },
                "level": "A2",
            },
            {
                "title": "Sentence Builder",
                "language": langs["en"],
                "type": Exercise.Type.SENTENCE,
                "prompt": "Соберите предложение.",
                "content": {"words": ["I", "have", "already", "done", "my", "homework"], "sentence": "I have already done my homework"},
                "level": "B1",
            },
            {
                "title": "Grammar: Articles",
                "language": langs["en"],
                "type": Exercise.Type.GRAMMAR,
                "prompt": "Выберите верный артикль: I saw ___ owl.",
                "content": {"options": ["a", "an", "the"], "correct": "an"},
                "level": "A2",
            },
            {
                "title": "Reading: Language café",
                "language": langs["en"],
                "type": Exercise.Type.READING,
                "prompt": "Прочитайте текст и ответьте на вопрос.",
                "content": {
                    "text": "Every Saturday DipLC opens a language café. Students bring snacks and talk only in the language they study.",
                    "questions": [
                        {
                            "prompt": "Когда открывается кафе?",
                            "options": ["Каждую субботу", "Каждый понедельник", "Раз в месяц"],
                            "correct": "Каждую субботу",
                            "type": "single",
                        }
                    ],
                },
                "level": "B1",
            },
            {
                "title": "Listening: Classroom phrases",
                "language": langs["en"],
                "type": Exercise.Type.LISTENING,
                "prompt": "Прослушайте аудио и впишите ключевую фразу преподавателя.",
                "content": {
                    "audio_url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
                    "questions": [{"prompt": "Какая тема урока?", "correct": "present perfect", "type": "fill_blank"}],
                },
                "level": "B1",
            },
            {
                "title": "Writing: My neighbourhood",
                "language": langs["en"],
                "type": Exercise.Type.WRITING,
                "prompt": "Опишите район, в котором вы живёте, 80–100 слов.",
                "content": {},
                "level": "B1",
            },
        ]
        for payload in exercises:
            Exercise.objects.get_or_create(title=payload["title"], defaults={**payload, "created_by": teachers[0]})

        ExerciseAttempt.objects.get_or_create(
            exercise=Exercise.objects.get(title="Vocabulary: Food"),
            student=students[0],
            defaults={"answers": "хлеб", "score": 100},
        )

        self.stdout.write(self.style.SUCCESS("Seed complete."))
