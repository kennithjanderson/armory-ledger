/* Shared ISO date entry and 24-hour presentation. Date-only values never use UTC conversion. */
(() => {
    const pad = value => String(value).padStart(2, "0");
    const months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
    const daysInMonth = (year, month) => [31, year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28, 31,30,31,30,31,31,30,31,30,31][month - 1];
    function validDate(value, monthOnly = false) {
        const match = (monthOnly ? /^(\d{4})-(\d{2})$/ : /^(\d{4})-(\d{2})-(\d{2})$/).exec(value);
        if (!match) return false;
        const [, y, m, d] = match.map(Number);
        return y >= 1 && m >= 1 && m <= 12 && (monthOnly || (d >= 1 && d <= daysInMonth(y, m)));
    }
    function formatLocal(value, seconds = false) {
        const date = value instanceof Date ? value : new Date(value);
        if (Number.isNaN(date.getTime())) return "";
        const result = `${String(date.getFullYear()).padStart(4,"0")}-${pad(date.getMonth()+1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
        return result + (seconds ? `:${pad(date.getSeconds())}` : "");
    }
    const instances = new WeakMap();
    function remove(input) { instances.get(input)?.remove(); instances.delete(input); }
    function enhance(input) {
        if (instances.has(input) || !["date", "month", "datetime-local"].includes(input.type)) return;
        const kind = input.type, timed = kind === "datetime-local", monthOnly = kind === "month";
        const originalValue = input.value, required = input.required;
        const wrapper = document.createElement("div"); wrapper.className = "date-picker";
        input.after(wrapper); wrapper.append(input);
        const date = timed ? document.createElement("input") : input;
        const label = document.querySelector(`label[for="${input.id}"]`);
        const labelText = label?.textContent.trim() || "Date";
        if (timed) {
            input.type = "hidden"; input.required = false;
            date.id = `${input.id}-date`; date.required = required;
            date.setAttribute("aria-label", `${labelText}: date (YYYY-MM-DD)`);
            if (label) label.htmlFor = date.id;
            wrapper.append(date);
        }
        date.type = "text"; date.placeholder = monthOnly ? "YYYY-MM" : "YYYY-MM-DD";
        date.pattern = monthOnly ? "[0-9]{4}-[0-9]{2}" : "[0-9]{4}-[0-9]{2}-[0-9]{2}";
        date.autocomplete = "off";
        const open = document.createElement("button"); open.type = "button";
        open.className = "button-secondary date-picker-open"; open.textContent = "Calendar";
        open.setAttribute("aria-label", `Choose ${labelText}`); open.setAttribute("aria-expanded", "false");
        wrapper.append(open);
        const panel = document.createElement("div"); panel.className = "date-picker-panel"; panel.hidden = true;
        panel.id = `${input.id}-calendar`; panel.setAttribute("role", "group"); panel.setAttribute("aria-label", `${labelText} calendar`);
        open.setAttribute("aria-controls", panel.id); wrapper.append(panel);
        const controls = document.createElement("div"); controls.className = "date-picker-navigation";
        const month = document.createElement("select"); month.setAttribute("aria-label", "Month");
        months.forEach((name,i)=>month.add(new Option(name,String(i+1))));
        const year = document.createElement("input"); year.type = "number"; year.min = "1"; year.max = "9999"; year.step = "1";
        year.setAttribute("aria-label", "Year");
        controls.append(month, year); panel.append(controls);
        const grid = document.createElement("div"); grid.className = "date-picker-days"; panel.append(grid);
        const close = () => { year.disabled = true; panel.hidden = true; open.setAttribute("aria-expanded", "false"); };
        function validate() {
            const valid = !date.value || validDate(date.value, monthOnly);
            const bounded = (!input.min || date.value >= input.min) && (!input.max || date.value <= input.max);
            date.setCustomValidity(valid && (!date.value || bounded) ? "" : `Enter a valid ${monthOnly ? "month" : "date"} in ${date.placeholder} format within the allowed range.`);
        }
        let hour, minute;
        function publish() {
            validate();
            if (timed) {
                input.value = date.value && hour.value !== "" && minute.value !== "" ? `${date.value}T${hour.value}:${minute.value}` : "";
                input.dispatchEvent(new Event("input", {bubbles:true}));
                input.dispatchEvent(new Event("change", {bubbles:true}));
            }
        }
        function choose(value) {
            date.value = value; close(); date.focus();
            date.dispatchEvent(new Event("input", {bubbles:true}));
            date.dispatchEvent(new Event("change", {bubbles:true}));
        }
        function draw() {
            grid.replaceChildren();
            const y = Number(year.value), m = Number(month.value);
            if (!Number.isInteger(y) || y < 1 || y > 9999) return;
            const prefix = `${String(y).padStart(4,"0")}-${pad(m)}`;
            if (monthOnly) {
                const button = document.createElement("button"); button.type="button"; button.textContent="Use this month";
                button.className="button-secondary"; button.addEventListener("click",()=>choose(prefix)); grid.append(button); return;
            }
            ["Su","Mo","Tu","We","Th","Fr","Sa"].forEach(day=>{ const heading=document.createElement("span");heading.textContent=day;grid.append(heading); });
            const first = new Date(0); first.setUTCFullYear(y,m-1,1);
            for(let i=0;i<first.getUTCDay();i++) grid.append(document.createElement("span"));
            for(let d=1;d<=daysInMonth(y,m);d++) {
                const value=`${prefix}-${pad(d)}`, button=document.createElement("button");
                button.type="button";button.textContent=String(d);button.dataset.date=value;
                button.setAttribute("aria-label",value);
                button.setAttribute("aria-pressed",String(date.value===value));
                button.disabled=Boolean((input.min && value<input.min)||(input.max && value>input.max));
                button.addEventListener("click",()=>choose(value));
                button.addEventListener("keydown",event=>{
                    const offsets={ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7};
                    if(!(event.key in offsets)) return;
                    event.preventDefault();
                    grid.querySelector(`[data-date="${prefix}-${pad(d+offsets[event.key])}"]`)?.focus();
                }); grid.append(button);
            }
        }
        open.addEventListener("click",()=>{
            if(!panel.hidden) {close();return;}
            const today=new Date(), parts=date.value.split("-");
            year.value=Number(parts[0]) || today.getFullYear(); month.value=String(Number(parts[1]) || today.getMonth()+1);
            year.disabled=false;draw();panel.hidden=false;open.setAttribute("aria-expanded","true");month.focus();
        });
        month.addEventListener("change",draw);year.addEventListener("input",draw);
        wrapper.addEventListener("keydown",event=>{if(event.key==="Escape"&&!panel.hidden){event.preventDefault();close();open.focus();}});
        wrapper.addEventListener("focusout",event=>{if(!wrapper.contains(event.relatedTarget))close();});
        date.addEventListener("input",publish);
        if(timed) {
            const time=document.createElement("div");time.className="date-picker-time";
            const legend=document.createElement("span");legend.textContent="Time (24-hour)";time.append(legend);
            const makeSelect=(name,count)=>{
                const select=document.createElement("select");select.required=required;
                select.setAttribute("aria-label",`${labelText}: ${name} (24-hour)`);
                select.add(new Option(name,""));
                for(let i=0;i<count;i++)select.add(new Option(pad(i),pad(i)));
                select.addEventListener("change",publish);time.append(select);return select;
            };
            hour=makeSelect("Hour",24);minute=makeSelect("Minute",60);wrapper.append(time);
        }
        function refresh() {
            if(timed) {
                const match=/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/.exec(input.value);
                date.value=match?.[1] || "";hour.value=match?.[2] || "";minute.value=match?.[3] || "";
            }
            validate();
        }
        input.value=originalValue;
        instances.set(input,{refresh,remove:()=>{
            date.removeEventListener("input",publish);
            wrapper.before(input);wrapper.remove();input.required=required;input.type=kind;input.setCustomValidity("");
            input.removeAttribute("pattern");if(label)label.htmlFor=input.id;
        }});
        refresh();
    }
    window.ArmoryDateTime={enhance,remove,refresh:input=>instances.get(input)?.refresh(),formatLocal,validDate};
    document.addEventListener("DOMContentLoaded",()=>document.querySelectorAll('input[type="date"],input[type="month"],input[type="datetime-local"]').forEach(enhance));
})();
