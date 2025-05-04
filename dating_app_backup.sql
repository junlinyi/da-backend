--
-- PostgreSQL database dump
--

-- Dumped from database version 14.17 (Homebrew)
-- Dumped by pg_dump version 14.17 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: dating_user
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


ALTER TABLE public.alembic_version OWNER TO dating_user;

--
-- Name: matches; Type: TABLE; Schema: public; Owner: dating_user
--

CREATE TABLE public.matches (
    id integer NOT NULL,
    user_id integer,
    matched_user_id integer,
    "timestamp" timestamp without time zone
);


ALTER TABLE public.matches OWNER TO dating_user;

--
-- Name: matches_id_seq; Type: SEQUENCE; Schema: public; Owner: dating_user
--

CREATE SEQUENCE public.matches_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.matches_id_seq OWNER TO dating_user;

--
-- Name: matches_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: dating_user
--

ALTER SEQUENCE public.matches_id_seq OWNED BY public.matches.id;


--
-- Name: swipes; Type: TABLE; Schema: public; Owner: dating_user
--

CREATE TABLE public.swipes (
    id integer NOT NULL,
    swiper_id integer NOT NULL,
    swiped_id integer NOT NULL,
    liked boolean,
    "timestamp" timestamp with time zone DEFAULT now()
);


ALTER TABLE public.swipes OWNER TO dating_user;

--
-- Name: swipes_id_seq; Type: SEQUENCE; Schema: public; Owner: dating_user
--

CREATE SEQUENCE public.swipes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.swipes_id_seq OWNER TO dating_user;

--
-- Name: swipes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: dating_user
--

ALTER SEQUENCE public.swipes_id_seq OWNED BY public.swipes.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: dating_user
--

CREATE TABLE public.users (
    id integer NOT NULL,
    email character varying NOT NULL,
    is_active boolean,
    bio text,
    age integer,
    gender character varying,
    interests character varying,
    location character varying,
    preferred_gender character varying,
    min_age_preference integer,
    max_age_preference integer,
    firebase_uid character varying NOT NULL
);


ALTER TABLE public.users OWNER TO dating_user;

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: dating_user
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.users_id_seq OWNER TO dating_user;

--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: dating_user
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: matches id; Type: DEFAULT; Schema: public; Owner: dating_user
--

ALTER TABLE ONLY public.matches ALTER COLUMN id SET DEFAULT nextval('public.matches_id_seq'::regclass);


--
-- Name: swipes id; Type: DEFAULT; Schema: public; Owner: dating_user
--

ALTER TABLE ONLY public.swipes ALTER COLUMN id SET DEFAULT nextval('public.swipes_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: dating_user
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: dating_user
--

COPY public.alembic_version (version_num) FROM stdin;
8e156c91bee2
\.


--
-- Data for Name: matches; Type: TABLE DATA; Schema: public; Owner: dating_user
--

COPY public.matches (id, user_id, matched_user_id, "timestamp") FROM stdin;
\.


--
-- Data for Name: swipes; Type: TABLE DATA; Schema: public; Owner: dating_user
--

COPY public.swipes (id, swiper_id, swiped_id, liked, "timestamp") FROM stdin;
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: dating_user
--

COPY public.users (id, email, is_active, bio, age, gender, interests, location, preferred_gender, min_age_preference, max_age_preference, firebase_uid) FROM stdin;
2	junlin.yi@icloud.com	t	\N	\N	\N	\N	\N	\N	18	100	Bas3uWN0XKNgU8lB7R93iZ2wiup1
3	tram.mhuy@gmail.com	t	\N	\N	\N	\N	\N	\N	18	100	O8qWCwHLCeUMIdA5HZnbMHhvgrv2
4	junlin.yi123@gmail.com	t	\N	\N	\N	\N	\N	\N	18	100	JJ3nBkDaosbDXkmm6JJWXCNlFoF2
\.


--
-- Name: matches_id_seq; Type: SEQUENCE SET; Schema: public; Owner: dating_user
--

SELECT pg_catalog.setval('public.matches_id_seq', 1, false);


--
-- Name: swipes_id_seq; Type: SEQUENCE SET; Schema: public; Owner: dating_user
--

SELECT pg_catalog.setval('public.swipes_id_seq', 1, false);


--
-- Name: users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: dating_user
--

SELECT pg_catalog.setval('public.users_id_seq', 4, true);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: dating_user
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: matches matches_pkey; Type: CONSTRAINT; Schema: public; Owner: dating_user
--

ALTER TABLE ONLY public.matches
    ADD CONSTRAINT matches_pkey PRIMARY KEY (id);


--
-- Name: swipes swipes_pkey; Type: CONSTRAINT; Schema: public; Owner: dating_user
--

ALTER TABLE ONLY public.swipes
    ADD CONSTRAINT swipes_pkey PRIMARY KEY (id);


--
-- Name: users users_firebase_uid_key; Type: CONSTRAINT; Schema: public; Owner: dating_user
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_firebase_uid_key UNIQUE (firebase_uid);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: dating_user
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: ix_swipes_id; Type: INDEX; Schema: public; Owner: dating_user
--

CREATE INDEX ix_swipes_id ON public.swipes USING btree (id);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: dating_user
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_id; Type: INDEX; Schema: public; Owner: dating_user
--

CREATE INDEX ix_users_id ON public.users USING btree (id);


--
-- Name: matches matches_matched_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: dating_user
--

ALTER TABLE ONLY public.matches
    ADD CONSTRAINT matches_matched_user_id_fkey FOREIGN KEY (matched_user_id) REFERENCES public.users(id);


--
-- Name: matches matches_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: dating_user
--

ALTER TABLE ONLY public.matches
    ADD CONSTRAINT matches_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: swipes swipes_swiped_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: dating_user
--

ALTER TABLE ONLY public.swipes
    ADD CONSTRAINT swipes_swiped_id_fkey FOREIGN KEY (swiped_id) REFERENCES public.users(id);


--
-- Name: swipes swipes_swiper_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: dating_user
--

ALTER TABLE ONLY public.swipes
    ADD CONSTRAINT swipes_swiper_id_fkey FOREIGN KEY (swiper_id) REFERENCES public.users(id);


--
-- PostgreSQL database dump complete
--

