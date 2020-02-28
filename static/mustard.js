import choc, {set_content} from "https://rosuav.github.io/shed/chocfactory.js";
const {B, TR, TD, BUTTON, DIV, OPTION, LI, INPUT, LABEL, IMG, SPAN} = choc;

const setupform = document.forms.setups.elements;
const schedform = document.forms.schedule.elements;

function render_setups() {
	const rows = setups.map((s, i) => TR({onclick: () => pick_setup(i)}, [
		TD(s.category),
		TD(s.title),
		TD(s.tags),
		TD(s.tweet),
		TD(BUTTON({className: "deleting", id: "del"+i}, "X")),
	]));
	const table = document.querySelector("#setups tbody");
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
	tweet: tweetbox.innerText,
});

function tidy_times(times) {
	times = times.replace(",", " ").split(" ");
	for (let i = 0; i < times.length; ++i)
	{
		const tm = times[i];
		//Reformat tm tidily
		//If tm is exactly "AM" or "PM" (case insensitively),
		//apply the transformation to the previous entry, and discard
		//this one. That will allow "9 pm" to parse correctly.
		//Edge case: "9  pm" still doesn't parse. Whatevs.
		const which = /^(AM)?(PM)?$/i.exec(tm);
		if (which && i && times[i-1] != "")
		{
			let [hr, min] = times[i-1].split(":");
			if (hr == "12") hr = "00";
			if (which[2]) hr = ("0" + (parseInt(hr, 10) + 12)).slice(-2);
			times[i-1] = hr + ":" + min;
			times[i] = "";
			continue;
		}
		//Yes, that's "?::" in a regex. Don't you just LOVE it when a
		//character is sometimes special, sometimes literal?
		//I'm abusing regex a little here; the last bit really should be
		//(AM|PM)?, but there's no way to say "but which of the alternation
		//did you match?". So by splitting it into two matchable parts, I
		//take advantage of the regex case-insensitivity flag. That DOES
		//mean that "2:30AMPM" will match. Simple rule: PM wins. (Just ask
		//Jim Hacker if you don't believe me. Except when he's PM.)
		const parts = /^([0-9][0-9]?)(?::([0-9][0-9]?))?(AM)?(PM)?$/i.exec(tm);
		if (!parts) {times[i] = ""; continue;} //Will end up getting completely suppressed
		let hour = parseInt(parts[1], 10);
		let min = parseInt(parts[2] || "00", 10);
		if (parts[3] || parts[4]) //AM or PM was set
		{
			if (hour == 12) hour = 0;
			if (parts[4]) hour += 12; //PM
		}
		times[i] = ("0" + hour).slice(-2) + ":" + ("0" + min).slice(-2);
	}
	return times.sort().join(" ").trim();
}

on("change", ".sched", e => schedule[e.match.name[5]] = e.match.value = tidy_times(e.match.value));

let tweet_to_send = "";
tweetbox.oninput = function() {
	let value = this.innerText;
	const sel = window.getSelection();
	const range = sel.rangeCount ? sel.getRangeAt(0).cloneRange() : document.createRange();
	range.setStart(this, 0);
	let cursor = range.toString().length; //Cursor position within the unstyled text.
	if (value.length > 280)
	{
		//The tweet needs to be broken up into a thread.
		//First, pick a split point. We favour newlines, then spaces,
		//and if all else fails, just take the first 280 characters.
		//Could be done with regex alternation, but that means we have more
		//capture groups and still have to figure out which group we caught.
		//If the /s (dotall) flag were supported, these [\s\S] units would be dots.
		const pieces = []; tweet_to_send = [];
		const colors = "#bbffbb #bbbbff #ffffbb #bbffff".split(" ");
		while (value.length > 280)
		{
			const match = /^([\s\S]{220,280}\n)([\s\S]{1,})$/m.exec(value) //A newline within the last 60 chars...
				|| /^([\s\S]{260,280} )([\s\S]{1,})$/m.exec(value) // ... or a space within the last 20...
				|| /^([\s\S]{280})([\s\S]*)$/m.exec(value); // ... or just break it right at the 280 mark.
			pieces.push(SPAN({style: "background-color: " + colors[pieces.length % colors.length]}, match[1]));
			tweet_to_send.push(match[1].trim());
			value = match[2];
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
	document.getElementById("tweetlen").innerHTML = value.length; //Length of the last portion
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
	]);
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
		document.forms.setups.classList.remove("dirty");
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
	document.getElementById("messages").scrollIntoView();
});

function timediff(timestr, date) {
	//Calculate the difference between a time string and a date.
	//Yes, it's weird. It's a helper for g_n_s_t below. Nothing more.
	//Can and will return a negative number of seconds if timestr
	//represents a time earlier in the day than date does.
	const [hr, min] = timestr.split(":");
	const tm = parseInt(hr, 10) * 60 + parseInt(min, 10);
	const secs = date.getHours() * 3600 + date.getMinutes() * 60 + date.getSeconds();
	return tm * 60 - secs;
}

function get_next_scheduled_time(offset) {
	//Returns [dow, time, days, tm]
	//dow - day of week (0-6)
	//time - HH:MM
	//days - number of days into the future (might be 0, might be 7)
	//tm - number of seconds from now until that time.
	//If no times on the schedule, returns [].
	const now = new Date(new Date() - (offset||0)*1000);
	const today = now.getDay(); //0 = Sunday, 1 = Monday, etc
	//Cycle from today forwards, wrapping, until we find a valid time
	//If we get all the way back to today, look at times behind us.
	const today_times = schedule[today].split(" ").filter(x => x);
	if (today_times.length) {
		//Find one that's after the current time
		const time = ("0" + now.getHours()).slice(-2) + ":" + ("0" + now.getMinutes()).slice(-2);
		for (let t of today_times) if (t > time) {
			return [today, t, 0, timediff(t, now)];
		}
	}
	//Nope? Okay, let's try tomorrow.
	for (let days = 1; days < 7; ++days) {
		const times = schedule[(today + days) % 7].split(" ").filter(x => x);
		if (times.length) return [(today + days) % 7, times[0], days, days*86400 + timediff(times[0], now)];
	}
	//Nothing at all? Alright, one last try, looking at today.
	//If there is anything at all on today's schedule, and we didn't return
	//from the previous block, then what we want is to wait all the way around
	//the week until we get back to today, and then take the earliest time
	//slot available. Seven days and negative a few hours.
	if (today_times.length) return [today, today_times[0], 7, 604800 + timediff(today_times[0], now)];
	//If we get here, the entire schedule must be empty.
	return [];
}

function format_schedule_time(offset) {
	const [dow, time, days, delay] = get_next_scheduled_time(offset);
	if (!time) return null;
	const hh = Math.floor(delay / 3600);
	const mm = ("0" + Math.floor((delay / 60) % 60)).slice(-2);
	const ss = ("0" + Math.floor(delay % 60)).slice(-2);
	const downame = "Sun Mon Tue Wed Thu Fri Sat".split(" ")[dow];
	let day;
	if (!days) day = "Today";
	else if (days == 1) day = "Tomorrow";
	else if (days == 7) day = "Next " + downame
	else day = downame;
	return `${day} ${time} ==> ${hh}:${mm}:${ss}`;
}

setInterval(function() {
	set_content("#nextsched", format_schedule_time() || "(none)");
	const when = document.getElementById("tweetschedule").value;
	set_content("#tweettime", when === "now" ? "Immediate" :
		format_schedule_time(+when) || "(need schedule)");
}, 1000);

function format_time(delay) {
	const mm = ("0" + Math.floor((delay / 60) % 60)).slice(-2);
	const ss = ("0" + Math.floor(delay % 60)).slice(-2);
	return mm + ":" + ss;
}

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

on("click", ".timer-adjust", e =>
	fetch("/timer-adjust-all/" + e.match.dataset.delta + "?channelid=" + channel._id, {credentials: "include"})
		.catch(err => console.error(err))
);
function force_timers(timestr) {
	const [min, sec] = timestr.split(":");
	const tm = parseInt(min, 10) * 60 + parseInt(sec||"0", 10);
	if (tm <= 0 || tm > 3600) return; //TODO: Handle these better
	fetch("/timer-force-all/" + tm + "?channelid=" + channel._id, {credentials: "include"})
		.catch(err => console.error(err));
}
document.getElementById("set-timer").onclick = () => force_timers(document.getElementById("targettime").value);
on("click", ".timer-force", e => force_timers(e.match.innerHTML));

const pickmapper = {
	game: game => LI({"data-pick": game.localized_name}, [IMG({src: game.box.small, alt: ""}), game.localized_name]),
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
	const cur = document.querySelector("section.current");
	let next = cur.previousElementSibling;
	if (next.tagName != "SECTION") {
		const all = document.querySelectorAll("section");
		next = all[all.length - 1];
	}
	next.classList.add("current");
	cur.classList.remove("current");
}
document.getElementById("next_section").onclick = () => {
	const cur = document.querySelector("section.current");
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
setupform.category.value = channel.game;
setupform.title.value = channel.status;
setupform.tags.value = channel.tags;
render_setups();
schedule.forEach((times, day) => schedform["sched" + day].value = tidy_times(times));
update_tweets(initial_tweets);

const local_tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
if (sched_tz === "") {
	//No saved TZ - assume you probably want the one you're using in the browser.
	schedform.sched_tz.value = local_tz;
} else {
	schedform.sched_tz.value = sched_tz;
	if (sched_tz !== local_tz) {
		//Your saved timezone and your browser timezone are different.
		//Notify the user.
		document.getElementById("othertz").innerHTML = "(Your browser's preferred timezone is: " + local_tz + ")";
	}
}

set_content("#checklist",
	document.forms.checklist.elements.checklist.value //provided by the server (via templating)
	.trim().split("\n")
	.map(item => item
		? LI(LABEL([INPUT({type: "checkbox"}), item]))
		: LI({className: "separator"}, "\xA0")
	)
);

//For browsers with only partial support for the <dialog> tag, add the barest minimum.
//On browsers with full support, there are many advantages to using dialog rather than
//plain old div, but this way, other browsers at least have it pop up and down.
document.querySelectorAll("dialog").forEach(dlg => {
	if (!dlg.showModal) dlg.showModal = function() {this.style.display = "block";}
	if (!dlg.close) dlg.close = function() {this.style.removeProperty("display");}
});
