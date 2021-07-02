import choc, {set_content, DOM, fix_dialogs} from "https://rosuav.github.io/shed/chocfactory.js";
const {A, B, TR, TD, BUTTON, DIV, OPTION, LI, INPUT, LABEL, IMG, SPAN} = choc;
fix_dialogs({close_selector: ".dialog_cancel,.dialog_close", click_outside: true});
import "https://cdn.jsdelivr.net/gh/twitter/twitter-text@3.1.0/js/pkg/twitter-text-3.1.0.min.js";
const parse_tweet = twttr.txt.parseTweet;

const setupform = document.forms.setups.elements;

//Map category names to their game IDs. If the to-be-saved category is in this
//mapping, we can send the ID to the server (as well as the category name) to
//save one API call.
const gameids = {[channel.game]: channel.game_id};

function render_setups() {
	const rows = setups.map((s, i) => TR({onclick: () => pick_setup(i)}, [
		TD(s.category),
		TD(s.title),
		TD(s.tags),
		TD(s.mature ? "Y" : "N"),
		TD(s.tweet),
		TD(BUTTON({className: "deleting", id: "del"+i}, "X")),
	]));
	const table = DOM("#setups tbody");
	rows.unshift(table.firstChild);
	set_content(table, rows);
}

let prevsetup = null;
const tweetbox = document.getElementById("tweet");
function pick_setup(i) {
	const setup = i === -1 ? prevsetup : setups[i];
	if (!setup) return; //Shouldn't happen
	setupform.category.value = setup.category;
	setupform.title.value = setup.title;
	setupform.tags.value = setup.tags;
	setupform.mature.checked = setup.mature;
	document.forms.setups.classList.add("dirty");
	if (setup.tweet && setup.tweet !== "") tweetbox.innerText = setup.tweet;
	tweetbox.oninput();
}

let deleting_setup = null;
let delete_time = 0;
on("click", ".deleting", async e => {
	if (deleting_setup != e.match.id) {
		//Await confirmation via a second click
		document.querySelectorAll(".deleting").forEach(b => b.innerHTML = "X");
		e.match.innerHTML = "Delete?";
		deleting_setup = e.match.id;
		delete_time = +new Date + 1;
		return;
	}
	if (+new Date < delete_time) return;
	//Okay, let's actually delete it.
	deleting_setup = null;
	e.match.innerHTML = "X";
	const result = await fetch("/api/setups/" + setups[e.match.id.slice(3)].id + "?channelid=" + channel._id, {
		credentials: "include",
		method: "DELETE",
	});
	if (!result.ok) return; //TODO: Show an error?
	setups = await (await fetch("/api/setups?channelid=" + channel._id, {credentials: "include"})).json();
	render_setups();
});

/*
document.getElementById("hello").onclick = async function() {
	const result = await (await fetch("/api/hello", {credentials: "include"})).json();
	console.log(result);
}
*/

async function save_setup(setup) {
	const result = await (await fetch("/api/setups?channelid=" + channel._id, {
		credentials: "include",
		headers: {"Content-Type": "application/json"},
		method: "POST",
		body: JSON.stringify(setup)
	})).json();
	setups.push(result);
	render_setups();
}
document.getElementById("save").onclick = () => save_setup({
	category: setupform.category.value,
	title: setupform.title.value,
	tags: setupform.tags.value,
	mature: setupform.mature.checked,
	tweet: tweetbox.innerText,
});

let tweet_to_send = "";
tweetbox.oninput = function() {
	let value = this.innerText;
	const sel = window.getSelection();
	const range = sel.rangeCount ? sel.getRangeAt(0).cloneRange() : document.createRange();
	range.setStart(this, 0);
	let cursor = range.toString().length; //Cursor position within the unstyled text.
	let parsed = parse_tweet(value);
	if (!parsed.valid)
	{
		//The tweet needs to be broken up into a thread.
		//First, pick a split point. We favour newlines, then spaces, and
		//if all else fails, just take the first N characters, where N is
		//whatever length the Twitter library says was valid.
		//Could be done with regex alternation, but that means we have more
		//capture groups and still have to figure out which group we caught.
		//If the /s (dotall) flag were supported, these [\s\S] units would be dots.
		const pieces = []; tweet_to_send = [];
		const colors = "#bbffbb #bbbbff #ffffbb #bbffff".split(" ");
		while (value.length && !parsed.valid)
		{
			const validpart = value.slice(0, parsed.validRangeEnd + 2); //Include one character beyond the limit, in case it's a space/newline
			const match = /^([\s\S]*\n)[\s\S]{0,60}?$/m.exec(validpart) //A newline within the last 60 chars...
				|| /^([\s\S]* )[\s\S]{0,20}?$/m.exec(validpart) // ... or a space within the last 20...
				|| [0, validpart]; // ... or just break it right at the 280 mark.
			pieces.push(SPAN({style: "background-color: " + colors[pieces.length % colors.length]}, match[1]));
			tweet_to_send.push(match[1].trim());
			value = value.slice(match[1].length);
			parsed = parse_tweet(value);
		}
		pieces.push(SPAN({style: "background-color: " + colors[pieces.length % colors.length]}, value));
		set_content(this, pieces);
		tweet_to_send.push(value.trim());
	}
	else
	{
		set_content(this, value); //Reset the colours
		tweet_to_send = value.trim(); //Just the text, not in an array
	}
	set_content("#tweetlen", parsed.weightedLength || "0"); //Length of the last portion
	//Find the place that this cursor position lands, possibly in one of the spans
	sel.removeAllRanges();
	let piece = this;
	if (!piece.firstChild) //Completely empty? Assume cursor is at 0.
	{
		range.setStart(this, 0); range.setEnd(this, 0);
		sel.addRange(range);
		return;
	}
	if (piece.firstChild.nodeType === 1) //Has child nodes, not just a text node
	{
		//Should this be done recursively?
		piece = piece.firstChild;
		while (cursor > piece.innerText.length)
		{
			cursor -= piece.innerText.length;
			piece = piece.nextSibling;
		}
	}
	range.setStart(piece.firstChild, cursor);
	range.setEnd(piece.firstChild, cursor);
	sel.addRange(range);
};

on("input", "form[name=setups] input", e => e.match.form.classList.add("dirty"));

function update_messages(result) {
	set_content("#messages", [
		result.error && DIV({className: "errormessage"}, result.error),
		result.warning && DIV({className: "warningmessage"}, result.warning),
		result.success && DIV({className: "successmessage"}, result.success),
	]).scrollIntoView();
}

const form_callbacks = {
	"^/tweet": (data, form) => {
		data.tweet = tweet_to_send;
	},
	"/tweet": (result, form) => {
		if (result.ok) {form.reset(); tweetbox.innerText = ""; tweetbox.oninput();} //Only clear the form if the tweet was sent
		select_tweet_schedule(sched_tweet);
		if (result.ok) update_tweets(result.new_tweets);
	},
	"/twitter_cfg": (result, form) => {
		form.closest("dialog").close();
		select_tweet_schedule(result.new_sched);
	},
	"^/update": (data, form) => {
		console.log(gameids);
		const id = gameids[data.category];
		if (id) data.game_id = id;
		data.mature = data.mature === "on"; //Use true/false for checkbox state rather than presence/absence
		console.log(data);
	},
	"/update": (result, form) => {
		if (!result.ok) return;
		//Attempt to replicate the sorting behaviour done on the server
		//It's okay if it isn't perfect, but most of the time, it'll be
		//right enough to avoid ugly flicker. If ever it's wrong, it's
		//what the server has that matters, and refreshing the page will
		//update the display to match that.
		const tags = form.elements.tags.value;
		const newtags = tags.split(",")
			.map(t => t.trim())
			.sort((a,b) => a.localeCompare(b))
			.join(", ");
		if (newtags !== tags) form.elements.tags.value = newtags;
		//Save the previous state as a temporary setup
		if (result.previous)
		{
			prevsetup = result.previous;
			set_content("#prevsetup", [
				SPAN("Previous setup:"),
				SPAN(prevsetup.category),
				SPAN(prevsetup.title),
				SPAN(prevsetup.tags),
				SPAN(BUTTON({onclick: () => pick_setup(-1)}, "Reapply")),
				SPAN(BUTTON({onclick: () => save_setup(prevsetup)}, "Save")),
			]).style.display = "block";
		}
		//The server can't update the Mature flag directly, but it does
		//let us know if it's currently set incorrectly.
		if (result.mature)
		{
			set_content("#maturedesc", [
				" " + result.mature + " ",
				//NOTE: If you're editing a different channel, this won't work.
				//It's not possible to change the Mature flag for someone else's
				//channel, but it'd be nice to reword the warning appropriately.
				A({href: "https://dashboard.twitch.tv/settings/stream", target: "_blank"}, "Toggle it here"),
			]).classList.add("warningmessage");
		}
		else set_content("#maturedesc", []).classList.remove("warningmessage");
		form.classList.remove("dirty");
	},
};

on("submit", "form.ajax", async ev => {
	const form = ev.match;
	ev.preventDefault();
	const dest = new URL(form.action);
	const data = {}; new FormData(form).forEach((v,k) => data[k] = v);
	const tweak = form_callbacks["^" + dest.pathname]; if (tweak) tweak(data, form);
	//console.log("Would submit:", data); return "neutered";
	const result = await (await fetch("/api" + dest.pathname + "?channelid=" + channel._id, {
		credentials: "include",
		headers: {"Content-Type": "application/json"},
		method: "POST",
		body: JSON.stringify(data)
	})).json();
	update_messages(result);
	const cb = form_callbacks[dest.pathname]; if (cb) cb(result, form);
});

function format_schedule_time(tm, offset) {
	const target = Date.parse(tm), now = +new Date();
	const targ = new Date(target);
	const time = ("0" + targ.getHours()).slice(-2) + ":" + ("0" + targ.getMinutes()).slice(-2);
	const downame = "Sun Mon Tue Wed Thu Fri Sat".split(" ")[targ.getDay()];
	//Subtract out the timezone offset to get us to local time, then round to the nearest
	//day. That gives us a date in days-since-1970 in local time. Note that this may give
	//odd results across a DST switch, since we use the same offset for both.
	const ofs = targ.getTimezoneOffset() * 60000;
	const days = Math.floor((target - ofs) / 86400000) - Math.floor((now - ofs) / 86400000);
	let day;
	if (!days) day = "Today";
	else if (days == 1) day = "Tomorrow";
	else if (days == 7) day = "Next " + downame;
	else day = downame;
	if (offset === "no-countdown") return day + " " + time;
	const delay = Math.floor((target - now) / 1000) + offset;
	const hh = Math.floor(delay / 3600);
	const mm = ("0" + Math.floor((delay / 60) % 60)).slice(-2);
	const ss = ("0" + Math.floor(delay % 60)).slice(-2);
	return `${day} ${time} ==> ${hh}:${mm}:${ss}`;
}

let schedule = [];
setInterval(function() {
	if (schedule.length) set_content("#upcoming_streams li:first-of-type .time", format_schedule_time(schedule[0].start_time, 0));
	const when = document.getElementById("tweetschedule").value;
	set_content("#tweettime", when === "now" ? "Immediate" :
		schedule.length ? format_schedule_time(schedule[0].start_time, +when) : "(need schedule)");
}, 1000);

function format_time(delay) {
	const mm = ("0" + Math.floor((delay / 60) % 60)).slice(-2);
	const ss = ("0" + Math.floor(delay % 60)).slice(-2);
	return mm + ":" + ss;
}

async function fetch_schedule() {
	const data = await (await fetch("/api/twitch_schedule?channelid=" + channel._id)).json();
	console.log("Got schedule:", data);
	schedule = data.schedule || [];
	if (!schedule.length) set_content("#upcoming_streams", LI("No scheduled streams - configure on your Twitch dashboard"));
	else set_content("#upcoming_streams", schedule.map(sch => LI([
		B({className: "time"}, format_schedule_time(sch.start_time, "no-countdown")),
		" - " + sch.title,
		//TODO: Box art for category, if applicable
		sch.category.name ? B(" - " + sch.category.name) : "",
	])));
}
on("click", "#fetch_schedule", fetch_schedule);
fetch_schedule();

function select_tweet_schedule(time) {
	const tweet = document.getElementById("tweetschedule");
	for (let opt of tweet) {
		if (opt.value == time) {tweet.value = time; return;}
	}
	//Guess we need to add an entry.
	let desc;
	if (time < 0) desc = "Custom: T-" + format_time(-time);
	else desc = "Custom: T+" + format_time(time);
	tweet.add(OPTION({value: time}, desc));
	tweet.value = time;
}

on("dragstart", ".timer-link", e => {
	const title = encodeURIComponent(e.match.innerText + " (MM)");
	const url = `${e.match.href}?layer-name=${title}&layer-width=470&layer-height=240`;
	e.dataTransfer.setData("text/uri-list", url);
});

on("click", ".timer-adjust", e =>
	fetch("/timer-adjust-all/" + e.match.dataset.delta + "?channelid=" + channel._id, {credentials: "include"})
		.catch(err => update_messages({error: err.message}))
);
function force_timers(timestr) {
	const [min, sec] = timestr.split(":");
	const tm = parseInt(min, 10) * 60 + parseInt(sec||"0", 10);
	if (tm <= 0 || tm > 3600) return update_messages({error: "Timers must be set to between 1 second and 1 hour"});
	fetch("/timer-force-all/" + tm + "?channelid=" + channel._id, {credentials: "include"})
		.catch(err => update_messages({error: err.message}));
}
document.getElementById("set-timer").onclick = () => force_timers(document.getElementById("targettime").value);
on("click", ".timer-force", e => force_timers(e.match.innerHTML));

const pickmapper = {
	game: game => LI({
		"data-pick": game.name,
		"data-pickid": gameids[game.name] = game.id, //Save the ID into the DOM (not currently used) and the lookup mapping
	}, [IMG({src: game.boxart, alt: ""}), game.name]),
	tag: tag => LI({"data-pick": tag.english_name}, [B(tag.english_name), ": " + tag.english_desc]),
};
let picking = "";
function open_picker(now_picking, heading) {
	picking = now_picking;
	document.getElementById("picker_search").value = "";
	document.getElementById("picker_results").innerHTML = "";
	document.getElementById("picker_heading").innerHTML = heading;
	document.getElementById("picker").showModal();
	document.getElementById("picker_search").oninput(); //Do an initial search immediately
}
document.getElementById("pick_cat").onclick = function(ev) {open_picker("game", "Pick a category:"); ev.preventDefault();}
document.getElementById("pick_tag").onclick = function(ev) {open_picker("tag", "Select tags:"); ev.preventDefault();}

let searching = false;
document.getElementById("picker_search").oninput = async function() {
	let val = this.value;
	if (searching) return;
	while (true)
	{
		try {
			searching = true;
			const res = await (await fetch(`/search/${picking}?q=` + encodeURIComponent(val))).json();
			set_content("#picker_results", res.map(pickmapper[picking]));
		}
		finally {
			searching = false;
		}
		//If the input has changed since we started searching, redo the search.
		if (val === this.value) break;
		val = this.value;
	}
}

on("click", "#picker_results li", ev => {
	const pick = ev.match.dataset.pick;
	if (picking === "game")
	{
		document.getElementById("category").value = pick;
		document.getElementById("picker").close();
	}
	else
	{
		const t = document.getElementById("tags");
		const tags = t.value.split(", "); //NOTE: The back end splits on "," and strips spaces.
		if (tags.includes(pick)) return; //Already got it
		tags.push(pick); tags.sort();
		while (tags[0] === "") tags.shift(); //Any empty string(s) should have sorted first
		t.value = tags.join(", ");
	}
	document.forms.setups.classList.add("dirty");
});
on("click", ".dialog_cancel", e => e.match.parentElement.close());

const twittercfg = document.forms.twittercfg.elements;
document.getElementById("twitter_config").onclick = ev => {
	ev.preventDefault();
	twittercfg.stdsched.value = "custom";
	twittercfg.custsched.value = sched_tweet;
	for (let opt of twittercfg.stdsched) {
		if (opt.value == sched_tweet) {
			twittercfg.stdsched.value = sched_tweet;
			twittercfg.custsched.value = "";
			break;
		}
	}
	twittercfg.stdsched.onchange();
	document.getElementById("twitter_cfg").showModal();
}
twittercfg.stdsched.onchange = function() {this.closest("ul").dataset.selval = this.value;};

document.getElementById("prev_section").onclick = () => {
	const cur = DOM("section.current");
	let next = cur.previousElementSibling;
	if (next.tagName != "SECTION") {
		const all = document.querySelectorAll("section");
		next = all[all.length - 1];
	}
	next.classList.add("current");
	cur.classList.remove("current");
}
document.getElementById("next_section").onclick = () => {
	const cur = DOM("section.current");
	let next = cur.nextElementSibling;
	if (next.tagName != "SECTION") next = document.querySelector("section"); //Loop back to start
	next.classList.add("current");
	cur.classList.remove("current");
}

on("keydown", "form", function(ev) {
	//On Ctrl-Enter, submit the form.
	//TODO: What do Mac users expect? Check specifically with Twitter.
	//If they expect Meta-Enter, can we handle that? Better still, is
	//there a generic event that we should be hooking?
	//NOTE: This won't work in Safari anyway, so we're talking about
	//Chrome or Firefox on a Mac.
	if (ev.ctrlKey && ev.keyCode === 13) ev.match.requestSubmit();
});

async function deltweet(ev, id) {
	ev.preventDefault();
	const result = await (await fetch("/api/tweet/" + id, {method: "DELETE", credentials: "include"})).json();
	update_messages(result);
	if (result.ok) update_tweets(result.new_tweets);
}

function format_multi_tweet(tweet) {
	if (typeof tweet === "string") return tweet;
	return tweet.join(" "); //Is this good enough? Or should it be coloured like in the input?
}

function update_tweets(tweets) {
	set_content("#tweets ul",
		tweets.map(([tm, id, tweet]) => LI([
			tm + ": " + format_multi_tweet(tweet) + " ",
			BUTTON({type: "button", onclick: ev => deltweet(ev, id)}, "Cancel"),
		]))
	);
	document.getElementById("tweets").classList.toggle("hidden", !tweets.length);
}

//Initialize display based on state provided by server
select_tweet_schedule(sched_tweet);
setupform.category.value = channel.game_name;
setupform.title.value = channel.title;
setupform.tags.value = channel.tags;
render_setups();
update_tweets(initial_tweets);

set_content("#checklist",
	document.forms.checklist.elements.checklist.value //provided by the server (via templating)
	.trim().split("\n")
	.map(item => item
		? LI(LABEL([INPUT({type: "checkbox"}), item]))
		: LI({className: "separator"}, "\xA0")
	)
);
