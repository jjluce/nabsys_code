##there are kinda two versions of this, 
##the overlay version (eg, isntrument audit or tag titration), showing system-wide means
##the single run version (eg, 16h data collection), showing per-channel data
##which complicates unifying things (eg, they use different input matrices for some of the similarly named plots...
##work towards: either one function with args, or two functions and a helper function to call one of the two main functions?

##########################################################################################################################################################################################

##helper function to extract run metadata from 30 character sample ID, and to create various Time fields
##need to update to non-positional extracts...
run_metrics_metadata_markup<-function(df){
df<-df%>%
	rename(any_of(c("Timestamp"="TimeStamp")))%>%	
	mutate(
		RunID= str_extract(df$filename,"(?<=(Metrics_)|(Data_)).+(?=.csv)") #extract between prefix and .csv
		,Sample= str_extract(RunID,"^.+?[-].+?(?=[-])") #biosample, extract from start of RunID to second dash (-). previously was str_sub(RunID,1,10)
		,Die= str_sub(RunID,27,29)
		,Wafer= str_extract(RunID,"[Ww].+(?=[-])") #extract between W or w and next dash (-). previously was str_sub(RunID,20,22)
		,Instrument= str_sub(RunID,24,26)
		,Injection= ifelse(grepl("_",RunID),str_extract(RunID,"[:alpha:][_].*$"),str_extract(RunID,"[:alpha:]$")) #if an underscore is found, take the last letter before the underscore to the end, otherwise take just the last letter. previously was str_sub(RunID,-1)
		,InjectionSample= paste(Injection,Sample)
		,WaferDie=paste(Wafer,Die,sep="-")
		)%>%
		group_by(filename)%>%
		mutate(
			##NB for time_min and time_sec, field is Timestamp in SystemMetrics and TimeStamp in ChannelData. dealing with this above by renaming to Timestamp
			Time_min=min(Timestamp) #the minimum timestamp per runID
			#,Time_min=ifelse(type=="SystemMetrics",min(Timestamp),min(TimeStamp)) #the minimum timestamp per runID
			,Time_sec=(as.numeric(Timestamp)-as.numeric(Time_min)) #for each row, compute time diff in seconds between row time and run t0
			#,Time_sec=as.numeric(ifelse(type=="SystemMetrics",Timestamp,TimeStamp))-as.numeric(Time_min) #for each row, compute time diff in seconds between row time and run t0
			,Time_minutes = as.numeric(Time_sec)/60 #create time in minutes
			,Time = as.numeric(Time_sec)/60/60 #create time in hours
			,Time_sec = round(Time_sec,0) #round seconds to whole number
		)%>%
		ungroup()
}

##########################################################################################################################################################################################

##helper function to collect Protocol settings file metadata from google sheets
build_protocol_settings_df<-function(){
S11_protocol_settings<-read_sheet("https://docs.google.com/spreadsheets/d/1w2ZVkmQjrU-1PeBAFNb9JDVsSd3hwGHqFD04JFTVQEw/edit?gid=1751227866#gid=1751227866",range="S11 - Automated Sample with Baselines")%>%
	mutate(ProtocolName="S11-Automated Sample Run with Baselines")%>%
	as_tibble()%>%
	mutate(
		CollectPressure=as.character(`Collect\nPressure`)
		,TargetBL_char=as.character(TargetBL)
	)%>%
	rename("SettingsGroup"=`Settings File Name`)%>%
	select(ProtocolName,SettingsGroup,TargetBL_char,CollectPressure)
S15_protocol_settings<-read_sheet("https://docs.google.com/spreadsheets/d/1w2ZVkmQjrU-1PeBAFNb9JDVsSd3hwGHqFD04JFTVQEw/edit?gid=1425828509#gid=1425828509",range="S15 - Automated Sample Run Static Bias")%>%
	mutate(ProtocolName="S15-Automated Sample Run Static Bias")%>%
	as_tibble()%>%
	mutate(
		CollectPressure=as.character(`Collect\nPressure`)
		,TargetBias_char=as.character(`Target Bias`)
	)%>%
	rename("SettingsGroup"=`Settings File Name`)%>%
	select(ProtocolName,SettingsGroup,TargetBias_char,CollectPressure)
protocol_settings<-bind_rows(S11_protocol_settings,S15_protocol_settings)%>%
	rename(`Target Baseline (mV)`="TargetBL_char",`Applied Pressure (psi)`="CollectPressure",`Target Bias (V)`=TargetBias_char)
return(protocol_settings)
}

##########################################################################################################################################################################################

##want to build file lists in a directory that have the same prefix, eg, "ChannelData_"
##requires: each experiment, or group of files to be assembled together, have to live together in the same folder
##actually, i guess maybe could create a first subset that matches to root sample ID(s), eg, KMC01-009; and then pulls that apart into separate lists
##for this first one, lets just assume experiment lives in its own folder (since i already did that), and, generally, that may be a better practice, idk.

overnight_run_plots<-function(){

library(patchwork)
library(gt)
library(googlesheets4)

protocols_settings<-build_protocol_settings_df()

experiment_dir<-dirname(file.choose())

output_file_timestamp<-format(Sys.time(),"_%Y%m%d_%H%M%S")

all_files<-list.files(experiment_dir,full.names=TRUE)
#view(all_files)
#clipr::write_clip(all_files)
##extract sample ids present by regex extract between the prefixes Data_ and Metrics_ and the suffix .csv; should tolerate sample id typos and such
run_batch<-as_tibble(all_files)%>%mutate(RunIDs=str_extract(value,"(?<=((Data)|(Metrics))_).+(?=\\.csv)"))%>%select(RunIDs)%>%unique()

ChannelData_files<-list.files(experiment_dir,pattern="ChannelData",full.names=TRUE)
SystemMetrics_files<-list.files(experiment_dir,pattern="SystemMetrics",full.names=TRUE)
RunData_files<-list.files(experiment_dir,pattern="RunData",full.names=TRUE)

SystemMetrics<-concat_csv_files(SystemMetrics_files) #long csv
ChannelData<-concat_csv_files(ChannelData_files) #very long csv
RunData<-concat_csv_files(RunData_files)

#test<-read_csv("//PROTON/TechDevGroup/Users/McElroy/run_metrics/20250429_tag_titration_human/SystemMetrics_KMC01-014A-02L58270w24-218G13a.csv")%>%
#	mutate(filename="SystemMetrics_KMC01-014A-02L58270w24-218G13a.csv")
#view(head(test,100))
#test2<-run_metrics_metadata_markup(test)
#view(head(test2,100))

SystemMetrics<-run_metrics_metadata_markup(SystemMetrics)
ChannelData<-run_metrics_metadata_markup(ChannelData)%>%filter(Time_sec %% 60 == 0) #immediately reduce to one line per minute of run time (tho a snapshot at that time, and not, eg, a rolling average)

#single overnight run:

for (run_id in as.list(run_batch$RunIDs)){
#for (file in SystemMetrics_files){
	#sample_data<-SystemMetrics%>%
	#	filter(filename==basename(file))
##panels from SystemMetrics csv (TERsys (system total event rate), E (active channel count), V (bias voltage), Cu (current + bias voltage), Norm_ER (event rate / active channel))
	sample_sys_data<-SystemMetrics%>%
		filter(RunID==run_id)
	max_sys_time_val<-max(sample_sys_data$Time)
	TERsys<-sample_sys_data |>
		ggplot(aes(Time, TotalEventRate)) +
		geom_point(color="hotpink", size=0.001) +
		labs(x = "Run Time (hrs)",
			y = "Total Event Rate (system)") +
		scale_x_continuous(limits=c(0,max_sys_time_val), breaks = seq(0, max_sys_time_val, by = 2)) +
		scale_y_continuous(limits=c(0,800), breaks = seq(0, 800, by = 200)) +
		theme_bw() +
		theme(legend.position = "none",
			axis.text.x = element_text(size = 5, color="black"), 
			axis.text.y = element_text(size = 5, color="black"),
			axis.ticks.x=element_line(linewidth=0.1),
			axis.ticks.y=element_line(linewidth=0.1),
			axis.title.x = element_text(size = 5, color="black"), 
			axis.title.y = element_text(size=5, color="black"))
	E<-sample_sys_data |>
		ggplot(aes(Time, ActiveChannelCount)) +
		geom_point(color="green", size=0.001) +
		labs(x = "Run Time (hrs)",
			y = "Active Channel Count") +
		scale_x_continuous(limits=c(0,max_sys_time_val), breaks = seq(0, max_sys_time_val, by = 2)) +
		scale_y_continuous(limits=c(0,260), breaks = seq(0, 260, by = 50)) +
		theme_bw() +
		theme(legend.position = "none",
			axis.text.x = element_text(size = 5, color="black"), 
			axis.text.y = element_text(size = 5, color="black"),
			axis.ticks.x=element_line(linewidth=0.1),
			axis.ticks.y=element_line(linewidth=0.1),
			axis.title.x = element_text(size = 5, color="black"), 
			axis.title.y = element_text(size=5, color="black"))
	V<-sample_sys_data |>
		ggplot(aes(Time, `BiasVoltage(V)`)) +
		geom_point(color="black", size=0.001) +
		labs(x = "Run Time (hrs)",
			y = "Bias Voltage (V)") +
		scale_x_continuous(limits=c(0,max_sys_time_val), breaks = seq(0, max_sys_time_val, by = 2)) +
		scale_y_continuous(limits=c(0,5), breaks = seq(0, 5, by = 0.5)) +
		theme_bw() +
		theme(legend.position = "none",
			axis.text.x = element_text(size = 5, color="black"), 
			axis.text.y = element_text(size = 5, color="black"),
			axis.ticks.x=element_line(linewidth=0.1),
			axis.ticks.y=element_line(linewidth=0.1),
			axis.title.x = element_text(size = 5, color="black"), 
			axis.title.y = element_text(size=5, color="black"))
	Cu<-sample_sys_data |>
		mutate(`Current(uA)`=as.numeric(`Current(A)`*1e6))|>
		ggplot(aes(x=Time)) +
		geom_point(aes(y=`Current(uA)`), color="darkblue", size=0.001) +
		geom_point(aes(y=(`BiasVoltage(V)`+(5/3))*30), color="orange", size=0.001) + 
		labs(x = "Run Time (hrs)") +
		scale_x_continuous(limits=c(0,max_sys_time_val), breaks = seq(0, max_sys_time_val, by = 2)) +
		scale_y_continuous(
			name="Current (uA)", limits=c(50,200), breaks = seq(50, 200, by = 25)
			,sec.axis=sec_axis(~.*(1/30)-(5/3),name="Bias Voltage (V)")
		) +
		annotate(geom="point",x=(.25*max_sys_time_val),y=200,color="darkblue",size=1.5)+
		annotate(geom="text",x=(.26*max_sys_time_val),y=200,label="Current (uA)", hjust="left",size=2.8)+
		annotate(geom="point",x=(.5*max_sys_time_val),y=200,color="orange",size=1.5)+
		annotate(geom="text",x=(.51*max_sys_time_val),y=200,label="Bias Voltage (V)", hjust="left",size=2.8)+
		theme_bw() +
		theme(legend.position = "none",
			axis.text.x = element_text(size = 5, color="black"), 
			axis.text.y = element_text(size = 5, color="black"),
			axis.ticks.x=element_line(linewidth=0.1),
			axis.ticks.y=element_line(linewidth=0.1),
			axis.title.x = element_text(size = 5, color="black"), 
			axis.title.y = element_text(size=5, color="darkblue"),
			axis.title.y.right= element_text(size=5,color="orange"))
	Norm_ER<-sample_sys_data |>
		mutate(TotalEventRate_norm=as.numeric(TotalEventRate)/as.numeric(ActiveChannelCount))
##run averages from SystemMetrics csv (system current, bias voltage, active channel count, total event rate)
	SysMetAvgs<-sample_sys_data |>
		summarize(
			`Current (uA)`=round(mean(as.numeric(`Current(A)`*1e6),na.rm=TRUE),0)
			,`Bias Voltage (V)`=round(mean(`BiasVoltage(V)`,na.rm=TRUE),1)
			,`Active Channel Count`=round(mean(ActiveChannelCount,na.rm=TRUE),0)
			,`Total Event Rate`=round(mean(TotalEventRate,na.rm=TRUE),0)
		)
##panels from ChannelData csv (per channel: total event rate (TER), CER (binned event rate + normalized event rate), channel viability (B), baseline (Base), RMS, LVL1)
	sample_channel_data<-ChannelData%>%
		filter(RunID==run_id)
	max_channel_time_val<-max(sample_channel_data$Time)
	TER<-sample_channel_data |>
		filter(ViableChannel=="TRUE")|>
		ggplot(aes(Time, TotalEventRate)) +
		geom_point(aes(color=as.factor(ChannelID)),size=0.001) +
		labs(x = "Run Time (hrs)",
			y = "Total Event Rate (channel)") +
		scale_x_continuous(limits=c(0,max_channel_time_val), breaks = seq(0, max_channel_time_val, by = 1)) +
		#scale_y_continuous(limits=c(0,max(sample_channel_data$TotalEventRate)), breaks = seq(0, max(sample_channel_data$TotalEventRate), by = 1)) +
		scale_y_continuous(limits=c(0,8), breaks = seq(0, 8, by = 1)) + #set upper limit to 8 for consistent plotting?
		theme_bw() +
		theme(legend.position = "none",
			axis.text.x = element_text(size = 5, color="black"), 
			axis.text.y = element_text(size = 5, color="black"),
			axis.ticks.x=element_line(linewidth=0.1),
			axis.ticks.y=element_line(linewidth=0.1),
			axis.title.x = element_text(size = 5, color="black"), 
			axis.title.y = element_text(size=5, color="black"))
	CER<-sample_channel_data |>
		filter(ViableChannel=="TRUE")|>
		mutate(x_bins = cut(ChannelID, breaks=5)) |>
		ggplot(aes(Time, TotalEventRate)) +
		geom_point(data=Norm_ER,aes(x=Time, y=TotalEventRate_norm), size=0.005, color="gray")+
		geom_smooth(aes(color=x_bins)) +
		labs(x = "Run Time (hrs)",
			y = "Total Event Rate") +
		scale_x_continuous(limits=c(0,max_channel_time_val), breaks = seq(0, max_channel_time_val, by = 1)) +
		#scale_y_continuous(limits=c(0,max(sample_channel_data$TotalEventRate)), breaks = seq(0, max(sample_channel_data$TotalEventRate), by = 1)) +
		scale_y_continuous(limits=c(0,6), breaks = seq(0, 6, by = 1)) + #set upper limit to 6 for consistent plotting?
		annotate(geom="point",x=0,y=6,color="gray",size=1)+
		annotate(geom="text",x=(.01*max_sys_time_val),y=6,label="Total event rate / Active channel count", hjust="left",size=2.8)+
		annotate(geom="point",x=(.5*max_sys_time_val),y=6,color="#F8766D",size=1,shape=15)+
		annotate(geom="text",x=(.51*max_sys_time_val),y=6,label="Ch1-51", hjust="left",size=2.2)+
		annotate(geom="point",x=(.6*max_sys_time_val),y=6,color="#A3A500",size=1,shape=15)+
		annotate(geom="text",x=(.61*max_sys_time_val),y=6,label="52-102", hjust="left",size=2.2)+
		annotate(geom="point",x=(.7*max_sys_time_val),y=6,color="#00BF7D",size=1,shape=15)+
		annotate(geom="text",x=(.71*max_sys_time_val),y=6,label="103-153", hjust="left",size=2.2)+
		annotate(geom="point",x=(.8*max_sys_time_val),y=6,color="#00B0F6",size=1,shape=15)+
		annotate(geom="text",x=(.81*max_sys_time_val),y=6,label="154-204", hjust="left",size=2.2)+
		annotate(geom="point",x=(.9*max_sys_time_val),y=6,color="#E76BF3",size=1,shape=15)+
		annotate(geom="text",x=(.91*max_sys_time_val),y=6,label="205-256", hjust="left",size=2.2)+
		theme_bw() +
		theme(legend.position = "none",
			axis.text.x = element_text(size = 5, color="black"), 
			axis.text.y = element_text(size = 5, color="black"),
			axis.ticks.x=element_line(linewidth=0.1),
			axis.ticks.y=element_line(linewidth=0.1),
			axis.title.x = element_text(size = 5, color="black"), 
			axis.title.y = element_text(size=5, color="black"))
	B<-sample_channel_data |>
		ggplot(aes(Time, ChannelID,color=ViableChannel)) +
		geom_point(size=0.001) +
		scale_color_manual(values=c("red","green")) +
		labs(x = "Run Time (hrs)",
			y = "Channel Viability") +
		scale_x_continuous(limits=c(0,max_channel_time_val), breaks = seq(0, max_channel_time_val, by = 1)) +
		scale_y_continuous(limits=c(0,260), breaks = seq(0, 260, by = 50)) +
		theme_bw() +
		theme(legend.position = "none",
			axis.text.x = element_text(size = 5, color="black"), 
			axis.text.y = element_text(size = 5, color="black"),
			axis.ticks.x=element_line(linewidth=0.1),
			axis.ticks.y=element_line(linewidth=0.1),
			axis.title.x = element_text(size = 5, color="black"), 
			axis.title.y = element_text(size=5, color="black"))
	Base_mean<-sample_channel_data |>
		filter(ViableChannel=="TRUE")|>
		group_by(Time) |>
		summarize(Mean=mean(Baseline,na.rm=TRUE))
	Base_plot<-sample_channel_data |>
		filter(ViableChannel=="TRUE")|>
		ggplot(aes(Time,Baseline)) +
		geom_point(color="deepskyblue", size=0.001) +
		geom_point(data=Base_mean,aes(Time,Mean),color="black",size=0.001) +
		labs(x = "Run Time (hrs)",
			y = "Baseline (mV)") +
		scale_x_continuous(limits=c(0,max_channel_time_val), breaks = seq(0, max_channel_time_val, by = 1)) +
		scale_y_continuous(limits=c(500,2500), breaks = seq(500, 2500, by = 500)) +
		theme_bw() +
		theme(legend.position = "none",
			axis.text.x = element_text(size = 5, color="black"), 
			axis.text.y = element_text(size = 5, color="black"),
			axis.ticks.x=element_line(linewidth=0.1),
			axis.ticks.y=element_line(linewidth=0.1),
			axis.title.x = element_text(size = 5, color="black"), 
			axis.title.y = element_text(size=5, color="black"))
	RMS<-sample_channel_data |>
		filter(ViableChannel=="TRUE")|> 
		filter(SignalRMS<0.08)|> #should check why this threshold value
		group_by(Time) |>
		mutate(Mean=mean(SignalRMS,na.rm=TRUE)) |>
		ggplot(aes(Time,Mean)) +
		geom_jitter(aes(Time,SignalRMS),color="darkslategray3",size=0.001) +
		geom_point(size=0.001) +
		labs(x = "Run Time (hrs)",
			y = "Signal RMS") +
		scale_x_continuous(limits=c(0,max_channel_time_val), breaks = seq(0, max_channel_time_val, by = 1)) +
		scale_y_continuous(limits=c(0,0.08)) +
		theme_bw() +
		theme(legend.position = "none",
			axis.text.x = element_text(size = 5, color="black"), 
			axis.text.y = element_text(size = 5, color="black"),
			axis.ticks.x=element_line(linewidth=0.1),
			axis.ticks.y=element_line(linewidth=0.1),
			axis.title.x = element_text(size = 5, color="black"), 
			axis.title.y = element_text(size=5, color="black"))
	LVL1<-sample_channel_data |>
		filter(ViableChannel=="TRUE")|> 
		filter(!(LevelOne==400))|> #could eval as LevelOne!=400? #NB, through mid-Nov 2025, this value had been 600, and was changed to 400 to roughly coincide with an OhmX controller software change
		group_by(Time) |>
		mutate(Mean=mean(LevelOne,na.rm=TRUE)) |>
		ungroup() |>
		ggplot(aes(Time,Mean)) +
		geom_jitter(aes(Time,LevelOne),color="orange",size=0.001) +
		geom_point(size=0.1) +
		labs(x = "Run Time (hrs)",
			y = "Level 1 (uV)") +
		scale_x_continuous(limits=c(0,max_channel_time_val), breaks = seq(0, max_channel_time_val, by = 1)) +
		scale_y_continuous(limits=c(300,1500)) +
		theme_bw() +
		theme(legend.position = "none",
			axis.text.x = element_text(size = 5, color="black"), 
			axis.text.y = element_text(size = 5, color="black"),
			axis.ticks.x=element_line(linewidth=0.1),
			axis.ticks.y=element_line(linewidth=0.1),
			axis.title.x = element_text(size = 5, color="black"), 
			axis.title.y = element_text(size=5, color="black"))
##run averages from ChannelData csv (LVL1_avg,Base_avg,RMS_avg,Viab_avg)
	ChannelAvgs<-sample_channel_data |>
		mutate(
			lvl1_clean=ifelse(((ViableChannel=="TRUE")&(LevelOne!=400)),LevelOne,NA) #NB, through mid-Nov 2025, this value had been 600, and was changed to 400 to roughly coincide with an OhmX controller software change
			,base_clean=ifelse((ViableChannel=="TRUE"),Baseline,NA)
			,rms_clean=ifelse((ViableChannel=="TRUE"),SignalRMS,NA)
		) |>
		summarize(
			`Channel Activity (%)`=round(100*(nrow(sample_channel_data%>%filter(ViableChannel=="TRUE"))/nrow(sample_channel_data)),0)
			,`Baseline (mV)`=round(mean(base_clean,na.rm=TRUE),0)
			,`Level 1 (uV)`=round(mean(lvl1_clean,na.rm=TRUE),0)
			,`Signal RMS`=round(mean(rms_clean,na.rm=TRUE),4)
		)
##run metadata from RunData csv (settings info)
	sample_run_data=RunData%>%
		filter(SampleID==run_id)%>%
		select(SampleID, ProtocolName, ReagentLot, SettingsGroup)%>%
		left_join(.,protocols_settings)%>%
		pivot_longer(c(`Target Baseline (mV)`,`Target Bias (V)`,`Applied Pressure (psi)`))%>%
		drop_na(value)%>%
		pivot_wider()%>%
		rename("Sample ID" = `SampleID`, "Protocol"=`ProtocolName`, "Settings" = `SettingsGroup`, "Reagent Lot" = `ReagentLot`)%>%
		relocate(`Settings`, .after=`Protocol`)%>%
		relocate(`Reagent Lot`, .after=`Applied Pressure (psi)`)
##assemble table
	table_data<-cbind(sample_run_data,ChannelAvgs,SysMetAvgs)%>%
		relocate(`Total Event Rate`,.before=`Channel Activity (%)`)%>%
		relocate(`Active Channel Count`,.after=`Channel Activity (%)`)%>%
		relocate(`Reagent Lot`,.before=`Total Event Rate`)
#text_table<-ggtexttable(table_data,rows=NULL,theme=ttheme(base_size=6))
protocol_cols<-as.character(colnames(sample_run_data%>%select(-`Sample ID`)))
Table_gt <- table_data |>
  gt() |> 
  tab_spanner(
    label = "Protocol Settings",
    columns = protocol_cols) %>%
    #columns = c(`Applied Pressure (psi)`, `Target Baseline (mV)`, `Protocol`, `Reagent Lot`)) %>%
  tab_spanner(
    label = "Average Values for Full Run",
    columns = c(`Total Event Rate`, `Channel Activity (%)`, `Active Channel Count`, `Baseline (mV)`, `Level 1 (uV)`, `Signal RMS`, `Current (uA)`, `Bias Voltage (V)`)
  )
Table_gt2 <- Table_gt |> 
    #tab_options(data_row.padding = px(0.3)) |>
  #opt_horizontal_padding(scale = 1) |>
 # opt_vertical_padding(scale = 0.3) |> 
  tab_options(table.font.size = 11) |> 
  tab_options(column_labels.padding = 8) |> 
  #tab_options(row_group.padding.horizontal = 2) |> 
  tab_options(table.font.color = "black") |> 
  #opt_stylize(style = 6) |> 
  tab_style(
    style = cell_fill(color = "lightblue"),
    locations = list(
      cells_column_spanners(matches("Protocol Settings")))) |> 
     tab_style(
    style = cell_fill(color = "lightgreen"),
    locations = list(
      cells_column_spanners(matches("Average Values for Full Run"))))


##layouts (patchwork) and save (ggplot2/tidyverse)
	(layout <- wrap_table(Table_gt2,space="fixed")  / #removed: wrap_elements(table_png) 
           (TER + B + Cu) / 
           (TERsys + CER + LVL1) /
           (E + RMS + Base_plot)
	& theme_minimal()
	& theme(legend.position = 'none')
	& theme(axis.title.x = element_text(size=8, color="black"))
	& theme(axis.title.y = element_text(size=8, color="black"))
	& theme(axis.text.x = element_text(size=7, color="black"))
	& theme(axis.text.y = element_text(size=7, color="black"))
	)
	ggsave(paste0(OUTPUT_BASE,run_id,"_overnight_instrument_metrics",output_file_timestamp,".jpg"),width=16.5,height=9)
}
}

##########################################################################################################################################################################################

##overlay version (eg, instrument audit, tag titration)
##shows system-wide avgs for multiple injections onto the same detector
##note: much of the initial sample read-in is common between the two versions.. might want, in the future, to split these out to a read-in function?

overlay_run_plots<-function(){

library(patchwork)
library(gt)

experiment_dir<-dirname(file.choose())

output_file_timestamp<-format(Sys.time(),"_%Y%m%d_%H%M%S")

all_files<-list.files(experiment_dir,full.names=TRUE)
##extract sample ids present by regex extract between the prefixes Data_ and Metrics_ and the suffix .csv; should tolerate sample id typos and such
##ah, but actually this is not used in this version?
#run_batch<-as_tibble(all_files)%>%mutate(RunIDs=str_extract(value,"(?<=((Data)|(Metrics))_).+(?=\\.csv)"))%>%select(RunIDs)%>%unique()

ChannelData_files<-list.files(experiment_dir,pattern="ChannelData",full.names=TRUE)
SystemMetrics_files<-list.files(experiment_dir,pattern="SystemMetrics",full.names=TRUE)
RunData_files<-list.files(experiment_dir,pattern="RunData",full.names=TRUE)

SystemMetrics<-concat_csv_files(SystemMetrics_files) #long csv
ChannelData<-concat_csv_files(ChannelData_files) #very long csv
RunData<-concat_csv_files(RunData_files)

SystemMetrics<-run_metrics_metadata_markup(SystemMetrics)
ChannelData<-run_metrics_metadata_markup(ChannelData)

#overlay runs:

##panels from SystemMetrics csv (TERsys (system total event rate), E (active channel count), Norm (normalized event rate), Cu (current)), Res (resistance kohms) , V (bias voltage)
######### System wide total event frequency #########
TERsys <- SystemMetrics |>
	group_by(Time_sec, RunIDRecord) |> 
	mutate(Mean=mean(TotalEventRate, na.rm=TRUE)) |>
	ungroup() |> 
	ggplot(aes(Time_minutes, Mean, color=Injection)) +
	geom_line(aes(group=`Injection`), linewidth=0.5) +
	labs(x = "Run Time (mins)",
		y = "Systemwide Total Event Rate") +
#    scale_x_continuous(limits=c(5, 15), breaks = seq(5, 15, by = 5)) +
#    scale_y_continuous(limits=c(0,800), breaks = seq(0, 800, by = 200)) + 
	facet_wrap(~WaferDie)

######### Active Channel Count #########
E <- SystemMetrics |>
	ggplot(aes(Time_minutes, ActiveChannelCount, color=Injection)) +
	geom_line(aes(group=`Injection`), linewidth=0.5) +
#    scale_x_continuous(limits=c(5, 15), breaks = seq(5, 15, by = 5)) +
	scale_y_continuous(limits=c(0,260), breaks = seq(0, 260, by = 50)) +
	labs(x = "Run Time (mins)",
		y = "Active Channel Count") +
	facet_wrap(~WaferDie)

######### Normalized event rate = System wide total event frequency / Active Channel Count #########
Norm <- SystemMetrics |>
	mutate(TotalEventRate_norm = as.numeric(TotalEventRate)/as.numeric(ActiveChannelCount)) |> 
	ggplot(aes(Time_minutes, TotalEventRate_norm, color=Injection)) +
	geom_line(aes(group=`Injection`), linewidth=0.5) +
#    scale_x_continuous(limits=c(5,15), breaks = seq(5, 15, by = 5)) +
#    scale_y_continuous(limits=c(0,3), breaks = seq(0, 3, by = 1)) +
	labs(x = "Run Time (mins)",
		y = " Systemwide Event Rate / \nActive Channel Count") +
	facet_wrap(~WaferDie)

######### Current (uA) #########   
Cu <- SystemMetrics |>
	mutate(`Current(A)`=as.numeric(`Current(A)`*1000000)) |> 
	ggplot(aes(Time_minutes, `Current(A)`, color=Injection)) +
	geom_line(aes(group=`Injection`), linewidth=0.5) +
#    scale_x_continuous(limits=c(5, 15), breaks = seq(5, 15, by = 5)) +
#    scale_y_continuous(limits=c(110,190), breaks = seq(110, 190, by = 20)) +
	labs(x = "Run Time (mins)",
		y = "Current (A)") +
	facet_wrap(~WaferDie)

######### Resistance (kOhms) #########  
Res <- SystemMetrics |>
	mutate(`Resistance (kOhms)`=as.numeric(`Resistance(Ohms)`/1000)) |> 
	ggplot(aes(Time_minutes, `Resistance (kOhms)`, color=Injection)) +
	geom_line(aes(group=`Injection`), linewidth=0.5) +
#    scale_x_continuous(limits=c(5, 15), breaks = seq(5, 15, by = 5)) +
#    scale_y_continuous(limits=c(22,26), breaks = seq(22, 26, by = 1)) +
	labs(x = "Run Time (mins)") +
	facet_wrap(~WaferDie)

######### Bias Voltage (V) #########  
V <- SystemMetrics |>
	ggplot(aes(Time_minutes, `BiasVoltage(V)`, color=Injection)) +
	geom_line(aes(group=`Injection`), linewidth=0.5) +
#    scale_x_continuous(limits=c(5, 15), breaks = seq(5, 15, by = 5)) +
#	scale_y_continuous(limits=c(2.5,4), breaks = seq(2.5, 4, by = 0.5)) +
	labs(x = "Run Time (mins)",
		y = "Bias Voltage (V)") +
	facet_wrap(~WaferDie)

#layout<-TERsys / V | E / Cu | Norm / Res
#layout

##panels from ChannelData csv (per channel: baseline (Base), RMS, LVL1, channel viability (B))
######### Measured Baselines (mV) #########  
Base <- ChannelData |>
	filter(ViableChannel=="TRUE") |> 
	group_by(Time_sec, RunIDRecord) |> 
	mutate(Mean=mean(Baseline, na.rm=TRUE)) |> 
	filter(ViableChannel=="TRUE") |> 
	ggplot(aes(Time_minutes, Mean, group=InjectionSample, color=Injection)) +
	geom_line(aes(group=`Injection`), linewidth=0.5) +
#    scale_x_continuous(limits=c(5, 15), breaks = seq(5, 15, by = 5)) +
#	scale_y_continuous(limits=c(750,1500), breaks = seq(750,1500, by = 250)) +
	labs(x = "Run Time (mins)",
		y = "Baseline (mV)") +
	facet_wrap(~WaferDie)

######### Signal RMS #########
RMS <- ChannelData |>
	filter(ViableChannel=="TRUE") |> 
	filter(SignalRMS < 0.1) |> 
	group_by(Time_sec, RunIDRecord) |> 
	#group_by(Time_minutes_floor, RunIDRecord) |> 
	mutate(Mean=mean(SignalRMS, na.rm=TRUE)) |>
	ggplot(aes(Time_minutes, Mean, group=InjectionSample, color=Injection)) +
	geom_line(linewidth=0.5) +
#    scale_x_continuous(limits=c(5,15), breaks = seq(5,15, by = 5)) +
	scale_y_continuous(limits=c(0,0.07), breaks = seq(0, 0.07, by = 0.02)) +
	labs(x = "Run Time (mins)",
		y = "Signal RMS") +
	facet_wrap(~WaferDie)

######### LVL1 #########
LVL1 <- ChannelData |>
	filter(ViableChannel=="TRUE") |> 
	filter(!(LevelOne==400.0000)) |> #NB, through mid-Nov 2025, this value had been 600, and was changed to 400 to roughly coincide with an OhmX controller software change
	group_by(Time) |> 
	mutate(Mean=mean(LevelOne, na.rm=TRUE)) |>
	ungroup() |> 
	ggplot(aes(Time_minutes, Mean, group=InjectionSample, color=Injection)) +
	geom_line(linewidth=0.5) +
#    scale_x_continuous(limits=c(5, 15), breaks = seq(5, 15, by = 5)) +
#    scale_y_continuous(limits=c(600,1200), breaks = seq(600, 1200, by = 100)) +
	labs(x = "Run Time (min)",
		y = "Level 1") +
	facet_wrap(~WaferDie)

######### Channel Viability #########
B <- ChannelData |> 
	ggplot(aes(Time_minutes, ChannelID, color=ViableChannel, group=Injection)) +
	geom_point(aes(Time_minutes, ChannelID, color=ViableChannel), size=0.001) +
	scale_color_manual(values=c("red", "green")) +
	scale_y_continuous(limits=c(0,260), breaks = seq(0, 260, by = 50)) +
#    scale_x_continuous(limits=c(5, 15), breaks = seq(5, 15, by = 5)) +
	labs(x = "Run Time (mins)",
		y = "Channel Viability") +
	facet_grid(vars(Injection), vars(WaferDie), scales ="free_x")

######### Put all the plots together #########  
layout <- TERsys / Base / V | E / RMS / Cu | Norm / LVL1 / Res | B 

######### Choose your final aesthetics and apply to all plots #########  
((layout + plot_layout(guides="collect")) 
  & theme_light()
  & theme(legend.position = 'top')
  & theme(legend.text = element_text(size = 12)) 
  & theme(legend.title = element_text(size = 12))
  & theme(axis.title.x = element_text(size = 11, color="black"))
  & theme(axis.title.y = element_text(size=11, color="black"))
  & theme(axis.text.x = element_text(size = 10, color="black"))
  & theme(axis.text.y = element_text(size = 10, color="black"))
  & theme(strip.background = element_blank())
  & theme(strip.text = element_text(size = 11, color="black"))
  )
batch_wafer_dies<-SystemMetrics%>%ungroup()%>%select(WaferDie)%>%unique()
save_name<-format_delim(batch_wafer_dies,"",eol="_")
ggsave(paste0(OUTPUT_BASE,save_name,"overlay_instrument_metrics",output_file_timestamp,".jpg"),width=14,height=8)
}

